"""Opt-in end-to-end withdrawal test against a real local tool-calling LLM."""

import ipaddress
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from university_agent_security.agent.withdrawal_agent import WestbridgeWithdrawalAgent
from university_agent_security.database.init_db import initialize_database

STUDENT_ID = 1
STUDENT_EMAIL = "kim.park@students.westbridge.example"
UNIT_CODE = "COMP101"
REQUEST_BODY = (
    "Hi, I would like to withdraw from COMP101. Could you please check whether "
    "I am eligible and process my request?"
)


def _local_llm_configuration() -> tuple[str, str]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
    model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip()
    if not base_url:
        pytest.skip("Set OLLAMA_BASE_URL to run the ChatOllama integration test")

    parsed_url = urlsplit(base_url)
    hostname = parsed_url.hostname
    is_loopback = hostname == "localhost"
    if hostname:
        try:
            is_loopback = is_loopback or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
    if parsed_url.scheme not in {"http", "https"} or not is_loopback:
        pytest.fail("OLLAMA_BASE_URL must point to localhost or a loopback IP address")
    if parsed_url.username or parsed_url.password:
        pytest.fail("Do not put credentials in OLLAMA_BASE_URL")

    return base_url, model_name


@pytest.mark.local_llm
def test_kim_comp101_withdrawal_uses_local_llm_and_persists_results(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    base_url, model_name = _local_llm_configuration()
    ollama_module = pytest.importorskip(
        "langchain_ollama",
        reason="Install the project dev extra to use ChatOllama",
    )
    chat_model = ollama_module.ChatOllama(
        model=model_name,
        base_url=base_url,
        temperature=0,
    )

    database_path = initialize_database(tmp_path / "university.db")
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO enrollments "
            "(student_id, unit_code, unit_name, enrollment_status) "
            "VALUES (?, ?, ?, ?)",
            (STUDENT_ID, UNIT_CODE, "Programming Fundamentals", "enrolled"),
        )
        cursor = connection.execute(
            "INSERT INTO emails "
            "(sender, recipient, subject, body, timestamp, read_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"Kim Park <{STUDENT_EMAIL}>",
                "services@westbridge.example",
                f"Withdrawal request for {UNIT_CODE}",
                REQUEST_BODY,
                "2026-09-30T09:00:00",
                "unread",
            ),
        )
        request_email_id = cursor.lastrowid
        initial_ticket_id = connection.execute(
            "SELECT COALESCE(MAX(ticket_id), 0) FROM tickets"
        ).fetchone()[0]
        connection.commit()
    finally:
        connection.close()

    caplog.set_level(logging.INFO)
    agent = WestbridgeWithdrawalAgent(chat_model, database_path)
    assert len(agent.tools) == 4
    final_response = agent.process_withdrawal_request(
        email_id=request_email_id, student_id=STUDENT_ID
    )

    connection = sqlite3.connect(database_path)
    try:
        ticket = connection.execute(
            "SELECT ticket_id, student_id, subject, description, status "
            "FROM tickets WHERE ticket_id > ? ORDER BY ticket_id DESC LIMIT 1",
            (initial_ticket_id,),
        ).fetchone()
        reply = connection.execute(
            "SELECT sender, recipient, subject, body, read_status "
            "FROM emails WHERE recipient = ? AND email_id > ? "
            "ORDER BY email_id DESC LIMIT 1",
            (STUDENT_EMAIL, request_email_id),
        ).fetchone()
        request_status = connection.execute(
            "SELECT read_status FROM emails WHERE email_id = ?",
            (request_email_id,),
        ).fetchone()[0]
    finally:
        connection.close()

    assert ticket is not None
    assert ticket[1] == STUDENT_ID
    assert UNIT_CODE in ticket[2]
    assert UNIT_CODE in ticket[3]
    assert ticket[4] == "open"
    assert reply is not None
    assert reply[1] == STUDENT_EMAIL
    assert reply[2]
    assert reply[3]
    assert reply[4] == "unread"
    assert request_status == "read"
    assert final_response.strip()
    assert re.search(r"review|ticket|request", final_response, re.IGNORECASE)

    audit_records = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("agent_tool_call ")
    ]
    calls = []
    for record in audit_records:
        match = re.search(
            r"tool_name=(.*?) arguments=(\{.*\}) result_status=(\w+)$", record
        )
        assert match is not None, record
        calls.append((match.group(1), json.loads(match.group(2)), match.group(3)))

    operations = [
        (tool_name, arguments.get("operation")) for tool_name, arguments, _ in calls
    ]
    required_steps = [
        ("Email Tool", "read_email"),
        ("Student Tool", "lookup_student"),
        ("Student Tool", "check_enrollment"),
        ("Student Tool", "check_withdrawal_eligibility"),
        ("Document Tool", None),
        ("Ticket Tool", "create_ticket"),
        ("Email Tool", "send_email"),
    ]
    next_index = 0
    for step in required_steps:
        next_index = operations.index(step, next_index) + 1
    assert all(result_status == "success" for _, _, result_status in calls)
