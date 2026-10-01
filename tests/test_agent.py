import logging
import sqlite3
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from university_agent_security.agent.withdrawal_agent import WestbridgeWithdrawalAgent
from university_agent_security.database.init_db import initialize_database


class ScriptedChatModel(BaseChatModel):
    """Offline model double that emits a predetermined LangChain tool-call flow."""

    _responses: list[AIMessage] = PrivateAttr(default_factory=list)
    _bound_tool_names: list[str] = PrivateAttr(default_factory=list)

    def __init__(self, responses: list[AIMessage]):
        super().__init__()
        self._responses = list(responses)

    @property
    def _llm_type(self) -> str:
        return "scripted-test-model"

    def bind_tools(self, tools, **kwargs):
        self._bound_tool_names = [tool.name for tool in tools]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        if not self._responses:
            raise AssertionError("Agent requested an unexpected model response")
        return ChatResult(generations=[ChatGeneration(message=self._responses.pop(0))])


def tool_call(name: str, arguments: dict[str, object], call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": arguments, "id": call_id, "type": "tool_call"}
        ],
    )


def test_withdrawal_agent_uses_exact_four_tools_and_completes_flow(
    tmp_path: Path, caplog
):
    database = initialize_database(tmp_path / "university.db")
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO emails "
            "(sender, recipient, subject, body, timestamp, read_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Kim Park <kim.park@students.westbridge.example>",
                "services@westbridge.example",
                "Withdrawal request for SEC101",
                "Please withdraw me from unit SEC101 this teaching period.",
                "2026-09-15T09:00:00",
                "unread",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    responses = [
        tool_call("email_tool", {"operation": "read_email", "email_id": 6}, "call-1"),
        tool_call(
            "student_tool", {"operation": "lookup_student", "student_id": 1}, "call-2"
        ),
        tool_call(
            "student_tool",
            {"operation": "check_enrollment", "student_id": 1, "unit_code": "SEC101"},
            "call-3",
        ),
        tool_call(
            "student_tool",
            {
                "operation": "check_withdrawal_eligibility",
                "student_id": 1,
                "unit_code": "SEC101",
            },
            "call-4",
        ),
        tool_call(
            "document_tool", {"query": "withdrawal deadlines eligibility"}, "call-5"
        ),
        tool_call(
            "ticket_tool",
            {
                "operation": "create_ticket",
                "student_id": 1,
                "subject": "Withdrawal request: SEC101",
                "description": "Review Kim Park's request to withdraw from SEC101.",
            },
            "call-6",
        ),
        tool_call(
            "email_tool",
            {
                "operation": "send_email",
                "recipient": "kim.park@students.westbridge.example",
                "subject": "SEC101 withdrawal request received",
                "body": "Your request was referred to the Registrar for review; this is not an approval.",
            },
            "call-7",
        ),
        AIMessage(
            content=(
                "Your SEC101 withdrawal request was referred to the Registrar for review. "
                "This is not an approval."
            )
        ),
    ]
    model = ScriptedChatModel(responses)
    caplog.set_level(logging.INFO)

    agent = WestbridgeWithdrawalAgent(model, database)
    final_response = agent.process_withdrawal_request(email_id=6, student_id=1)

    assert len(agent.tools) == 4
    assert {tool.name for tool in agent.tools} == {
        "email_tool",
        "student_tool",
        "document_tool",
        "ticket_tool",
    }
    assert model._bound_tool_names == [tool.name for tool in agent.tools]
    assert not model._responses
    assert "referred to the Registrar" in final_response
    assert "not an approval" in final_response

    connection = sqlite3.connect(database)
    try:
        ticket = connection.execute(
            "SELECT student_id, subject, status FROM tickets ORDER BY ticket_id DESC LIMIT 1"
        ).fetchone()
        response_email = connection.execute(
            "SELECT recipient, subject, body FROM emails WHERE subject = ?",
            ("SEC101 withdrawal request received",),
        ).fetchone()
        read_status = connection.execute(
            "SELECT read_status FROM emails WHERE email_id = ?", (6,)
        ).fetchone()[0]
    finally:
        connection.close()

    assert ticket == (1, "Withdrawal request: SEC101", "open")
    assert response_email is not None
    assert response_email[0] == "kim.park@students.westbridge.example"
    assert read_status == "read"

    audit_records = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("agent_tool_call ")
    ]
    assert len(audit_records) == 7
    assert all("timestamp=" in record for record in audit_records)
    assert all("arguments=" in record for record in audit_records)
    assert all("result_status=success" in record for record in audit_records)
    assert not any("chain-of-thought" in record.casefold() for record in audit_records)


def test_withdrawal_agent_rejects_invalid_request_ids():
    model = ScriptedChatModel([])
    agent = WestbridgeWithdrawalAgent(model)

    try:
        agent.process_withdrawal_request(email_id=True, student_id=1)
    except ValueError as error:
        assert "email_id" in str(error)
    else:
        raise AssertionError("Boolean email ID should be rejected")
