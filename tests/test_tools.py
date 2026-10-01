import json
import logging
import sqlite3
from pathlib import Path

import pytest

from university_agent_security.database.init_db import initialize_database
from university_agent_security.document_search import POLICY_DIRECTORY
from university_agent_security.tools.document_tool import DocumentTool
from university_agent_security.tools.email_tool import EmailTool
from university_agent_security.tools.student_tool import StudentTool
from university_agent_security.tools.ticket_tool import TicketTool


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return initialize_database(tmp_path / "university.db")


def read_database_row(
    database_path: Path, query: str, parameters: tuple[object, ...]
) -> sqlite3.Row | None:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query, parameters).fetchone()
    finally:
        connection.close()


class ConnectionRecorder:
    def __init__(
        self,
        connection: sqlite3.Connection,
        statements: list[tuple[str, tuple[object, ...]]],
    ):
        self.connection = connection
        self.statements = statements

    @property
    def row_factory(self):
        return self.connection.row_factory

    @row_factory.setter
    def row_factory(self, factory):
        self.connection.row_factory = factory

    def execute(self, query: str, parameters=()):
        bound_parameters = tuple(parameters)
        self.statements.append((query, bound_parameters))
        return self.connection.execute(query, parameters)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exception_type, exception, traceback):
        return self.connection.__exit__(exception_type, exception, traceback)


def test_email_tool_valid_operations_and_persistence(database_path: Path):
    tool = EmailTool(database_path)

    read_result = tool.read_email(2)
    assert read_result.success
    assert read_result.emails[0].read_status == "read"

    search_result = tool.search_emails(
        "reading list", recipient="kim.park@students.westbridge.example"
    )
    assert search_result.success
    assert search_result.emails[0].subject == "SEC101 reading list"

    sent_result = tool.send_email(
        "kim.park@students.westbridge.example",
        "Schedule update",
        "The fictional seminar starts at 10:00.",
    )
    assert sent_result.success
    stored_email = read_database_row(
        database_path,
        "SELECT sender, recipient, subject, body, read_status FROM emails WHERE email_id = ?",
        (sent_result.emails[0].email_id,),
    )
    assert stored_email is not None
    assert stored_email["recipient"] == "kim.park@students.westbridge.example"
    assert stored_email["subject"] == "Schedule update"
    assert stored_email["body"] == "The fictional seminar starts at 10:00."
    assert stored_email["read_status"] == "unread"


def test_email_tool_rejects_invalid_inputs(database_path: Path):
    tool = EmailTool(database_path)

    assert tool.read_email(True).error_code == "invalid_input"
    assert tool.search_emails(" ").error_code == "invalid_input"
    assert tool.search_emails("notice", limit=0).error_code == "invalid_input"
    assert tool.send_email("", "Subject", "Body").error_code == "invalid_input"
    assert (
        tool.send_email("kim@westbridge.example", " ", "Body").error_code
        == "invalid_input"
    )
    assert (
        tool.send_email("kim@westbridge.example", "Subject", " ").error_code
        == "invalid_input"
    )


def test_student_tool_valid_operations_and_invalid_student_ids(database_path: Path):
    tool = StudentTool(database_path)

    profile = tool.lookup_student(1)
    assert profile.success
    assert profile.data == {
        "student_id": 1,
        "first_name": "Kim",
        "last_name": "Park",
        "email": "kim.park@students.westbridge.example",
        "course": "BSc Cybersecurity",
        "status": "active",
    }
    assert tool.check_enrollment(1, "SEC101").data["is_enrolled"] is True
    assert tool.check_enrollment(1, "SEC999").data["is_enrolled"] is False
    assert tool.check_withdrawal_eligibility(1, "SEC101").data["eligible"] is True

    assert tool.lookup_student(0).error_code == "invalid_input"
    assert tool.lookup_student(True).error_code == "invalid_input"
    assert tool.lookup_student(999).error_code == "not_found"
    assert tool.check_enrollment(1, "bad code").error_code == "invalid_input"
    assert tool.check_withdrawal_eligibility(999, "SEC101").error_code == "not_found"


def test_document_tool_searches_local_policies():
    tool = DocumentTool()

    result = tool.search_documents("withdrawal deadline")
    assert result.success
    assert result.sections[0].filename == "withdrawal_policy.md"
    assert result.sections[0].section_title == "Deadlines"
    assert "week 6" in result.sections[0].text.casefold()
    assert (
        tool.search_documents("assessment extension").sections[0].filename
        == "assessment_policy.md"
    )
    assert tool.search_documents(" ").error_code == "invalid_input"
    assert tool.search_documents("xylophone").sections == ()
    assert POLICY_DIRECTORY.is_dir()


def test_ticket_tool_valid_operations_and_persistence(database_path: Path):
    tool = TicketTool(database_path)
    created = tool.create_ticket(
        1, "Access card question", "Please explain the replacement process."
    )

    assert created.success
    assert created.ticket.status == "open"
    stored_ticket = read_database_row(
        database_path,
        "SELECT student_id, subject, description, status FROM tickets WHERE ticket_id = ?",
        (created.ticket.ticket_id,),
    )
    assert stored_ticket is not None
    assert stored_ticket["student_id"] == 1
    assert stored_ticket["subject"] == "Access card question"
    assert stored_ticket["description"] == "Please explain the replacement process."

    retrieved = tool.get_ticket(created.ticket.ticket_id)
    assert retrieved.success
    assert retrieved.ticket.subject == "Access card question"
    updated = tool.update_ticket_status(created.ticket.ticket_id, "in_progress")
    assert updated.success
    assert updated.ticket.status == "in_progress"


def test_ticket_tool_rejects_invalid_inputs(database_path: Path):
    tool = TicketTool(database_path)

    assert tool.create_ticket(0, "Subject", "Description").error_code == "invalid_input"
    assert (
        tool.create_ticket(True, "Subject", "Description").error_code == "invalid_input"
    )
    assert tool.create_ticket(999, "Subject", "Description").error_code == "not_found"
    assert tool.create_ticket(1, " ", "Description").error_code == "invalid_input"
    assert tool.create_ticket(1, "Subject", " ").error_code == "invalid_input"
    assert (
        tool.create_ticket(1, "Subject\nOther", "Description").error_code
        == "invalid_input"
    )
    assert tool.get_ticket(0).error_code == "invalid_input"
    assert tool.get_ticket(999).error_code == "not_found"
    assert tool.update_ticket_status(1, "unknown").error_code == "invalid_input"


def test_tool_results_do_not_expose_sqlite_connections(database_path: Path):
    tools_and_results = [
        (EmailTool(database_path), EmailTool(database_path).read_email(1)),
        (StudentTool(database_path), StudentTool(database_path).lookup_student(1)),
        (DocumentTool(), DocumentTool().search_documents("withdrawal")),
        (TicketTool(database_path), TicketTool(database_path).get_ticket(1)),
    ]

    for tool, result in tools_and_results:
        assert not isinstance(result, sqlite3.Connection)
        assert not hasattr(tool, "connection")
        assert "connection" not in result.to_dict()
        json.dumps(result.to_dict())


def test_sql_queries_bind_values(database_path: Path, monkeypatch: pytest.MonkeyPatch):
    statements: list[tuple[str, tuple[object, ...]]] = []
    sqlite_connect = sqlite3.connect

    def recording_connect(*args, **kwargs):
        return ConnectionRecorder(sqlite_connect(*args, **kwargs), statements)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)

    EmailTool(database_path).send_email(
        "kim.park@students.westbridge.example",
        "Bound email subject",
        "Bound email body",
    )
    EmailTool(database_path).search_emails(
        "Bound search phrase", recipient="kim.park@students.westbridge.example"
    )
    StudentTool(database_path).lookup_student(1)
    StudentTool(database_path).check_enrollment(1, "SEC101")
    TicketTool(database_path).create_ticket(
        1, "Bound ticket subject", "Bound ticket description"
    )
    TicketTool(database_path).get_ticket(1)
    TicketTool(database_path).update_ticket_status(1, "resolved")

    data_queries = [
        (query, parameters)
        for query, parameters in statements
        if query.lstrip().split(maxsplit=1)[0].upper() in {"SELECT", "INSERT", "UPDATE"}
    ]
    assert data_queries
    assert all("?" in query for query, _ in data_queries)
    assert all(
        query.count("?") == len(parameters) for query, parameters in data_queries
    )


def test_tool_invocations_are_logged(
    database_path: Path, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    EmailTool(database_path).read_email(1)
    StudentTool(database_path).lookup_student(1)
    DocumentTool().search_documents("withdrawal")
    TicketTool(database_path).get_ticket(1)

    messages = [record.getMessage() for record in caplog.records]
    assert any("email_tool.read_email invoked" in message for message in messages)
    assert any("student_tool.lookup_student invoked" in message for message in messages)
    assert any(
        "document_tool.search_documents invoked" in message for message in messages
    )
    assert any("ticket_tool.get_ticket invoked" in message for message in messages)
