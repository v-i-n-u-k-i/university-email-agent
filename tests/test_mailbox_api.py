import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from university_agent_security.api.app import create_app
from university_agent_security.database.init_db import initialize_database
from university_agent_security.tools.email_tool import EmailTool


class ReplyingAgent:
    def __init__(self, email_tool: EmailTool, on_tool_activity) -> None:
        self.email_tool = email_tool
        self.on_tool_activity = on_tool_activity
        self.calls: list[tuple[int, int]] = []

    def process_withdrawal_request(self, email_id: int, student_id: int) -> str:
        self.calls.append((email_id, student_id))
        self.on_tool_activity("Email Tool", "read_email")
        self.on_tool_activity("Student Tool", "lookup_student")
        self.on_tool_activity("Student Tool", "check_enrollment")
        self.on_tool_activity("Student Tool", "check_withdrawal_eligibility")
        self.on_tool_activity("Document Tool", "search_documents")
        self.on_tool_activity("Ticket Tool", "create_ticket")
        self.on_tool_activity("Email Tool", "send_email")
        result = self.email_tool.send_email(
            "kim.park@students.westbridge.example",
            "Your request is with Student Services",
            "Your message was received and referred for review.",
        )
        assert result.success
        return "Your message was received and referred for review."


def test_local_mailbox_sends_to_agent_and_shows_reply(tmp_path: Path):
    database = initialize_database(tmp_path / "university.db")
    email_tool = EmailTool(database)
    agent = None

    def make_agent(on_tool_activity):
        nonlocal agent
        agent = ReplyingAgent(email_tool, on_tool_activity)
        return agent

    client = TestClient(create_app(email_tool, make_agent))

    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "Westbridge Student Mail" in homepage.text

    response = client.post(
        "/api/emails",
        json={
            "recipient": "fake_uni@westbridge.edu",
            "subject": "Withdrawal request",
            "body": "Please review my request to withdraw from SEC101.",
        },
    )
    assert response.status_code == 202, response.text
    sent_message = response.json()["sent_email"]
    assert sent_message["recipient"] == "fake_uni@westbridge.edu"
    assert "Kim Park" in sent_message["sender"]
    activity = client.get(f"/api/activity/{response.json()['job_id']}")
    assert activity.status_code == 200
    for status in (
        "Email received",
        "Reading email",
        "Checking student eligibility",
        "Searching withdrawal policy",
        "Creating support ticket",
        "Sending response",
        "Request completed",
    ):
        assert status in activity.text
    assert '"tool": "Email Tool"' in activity.text
    assert '"tool": "Student Tool"' in activity.text
    assert agent is not None
    assert agent.calls == [(sent_message["email_id"], 1)]

    sent_folder = client.get("/api/mailbox/sent").json()["emails"]
    assert any(
        message["email_id"] == sent_message["email_id"] for message in sent_folder
    )

    inbox = client.get("/api/mailbox/inbox").json()["emails"]
    reply = next(
        message
        for message in inbox
        if message["subject"] == "Your request is with Student Services"
    )
    assert reply["recipient"] == "kim.park@students.westbridge.example"

    opened = client.get(f"/api/emails/{reply['email_id']}")
    assert opened.status_code == 200
    assert opened.json()["email"]["read_status"] == "read"

    connection = sqlite3.connect(database)
    try:
        stored = connection.execute(
            "SELECT sender, recipient, subject, body FROM emails WHERE email_id = ?",
            (sent_message["email_id"],),
        ).fetchone()
    finally:
        connection.close()
    assert stored[1] == "fake_uni@westbridge.edu"
    assert stored[2] == "Withdrawal request"


def test_mailbox_rejects_other_recipients_without_sending(tmp_path: Path):
    email_tool = EmailTool(initialize_database(tmp_path / "university.db"))
    factory_calls = []

    def make_agent(on_tool_activity):
        factory_calls.append(True)
        return ReplyingAgent(email_tool, on_tool_activity)

    client = TestClient(create_app(email_tool, make_agent))
    sent_before = client.get("/api/mailbox/sent").json()["emails"]

    response = client.post(
        "/api/emails",
        json={
            "recipient": "someone@example.com",
            "subject": "Hello",
            "body": "This should stay local.",
        },
    )

    assert response.status_code == 422
    assert factory_calls == []
    assert client.get("/api/mailbox/sent").json()["emails"] == sent_before
