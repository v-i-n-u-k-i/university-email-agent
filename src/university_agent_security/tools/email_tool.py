"""Validated local email operations for the Westbridge University agent."""

import logging
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import getaddresses
from pathlib import Path

LOGGER = logging.getLogger(__name__)
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[3] / "data" / "university.db"
DEFAULT_SENDER = "security-agent@westbridge.example"
STUDENT_INBOX_ADDRESS = "fake_uni@westbridge.edu"
MAX_SEARCH_RESULTS = 100
MAX_SUBJECT_LENGTH = 998
MAX_BODY_LENGTH = 50_000
SQLITE_BUSY_TIMEOUT_SECONDS = 30
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class EmailRecord:
    """A serializable email row returned by the tool."""

    email_id: int
    sender: str
    recipient: str
    subject: str
    body: str
    timestamp: str
    read_status: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class EmailToolResult:
    """Structured result shared by all public email operations."""

    success: bool
    action: str
    emails: tuple[EmailRecord, ...] = ()
    error_code: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "action": self.action,
            "emails": [email.to_dict() for email in self.emails],
            "error_code": self.error_code,
            "error": self.error,
        }


class EmailTool:
    """Read, search, and send emails using the local SQLite database only."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path).resolve()
        if self.database_path.is_file():
            try:
                with closing(
                    sqlite3.connect(
                        self.database_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS
                    )
                ) as connection:
                    connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError:
                LOGGER.warning(
                    "Could not switch the local email database to WAL mode; "
                    "continuing with the configured busy timeout"
                )

    def read_email(self, email_id: int) -> EmailToolResult:
        """Return one email and mark it as read."""
        action = "read_email"
        LOGGER.info("email_tool.%s invoked", action)
        if isinstance(email_id, bool) or not isinstance(email_id, int) or email_id < 1:
            return self._failure(
                action, "invalid_input", "email_id must be a positive integer"
            )

        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "UPDATE emails SET read_status = 'read' WHERE email_id = ?",
                    (email_id,),
                )
                row = connection.execute(
                    "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
                    "FROM emails WHERE email_id = ?",
                    (email_id,),
                ).fetchone()
            if row is None:
                return self._failure(
                    action, "not_found", "No email exists with that email_id"
                )
            return self._success(action, (self._record(row),))
        except sqlite3.Error:
            LOGGER.exception("email_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local email database is unavailable"
            )

    def search_emails(
        self,
        query: str,
        recipient: str | None = None,
        limit: int = 20,
    ) -> EmailToolResult:
        """Search sender, recipient, subject, and body for a keyword substring."""
        action = "search_emails"
        LOGGER.info("email_tool.%s invoked", action)
        if not isinstance(query, str) or not query.strip():
            return self._failure(
                action, "invalid_input", "query must be a non-empty string"
            )
        normalized_recipient = None
        if recipient is not None:
            normalized_recipient = self._normalize_email(recipient)
            if normalized_recipient is None:
                return self._failure(
                    action, "invalid_input", "recipient must be a valid email address"
                )
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_SEARCH_RESULTS
        ):
            return self._failure(
                action,
                "invalid_input",
                f"limit must be an integer from 1 to {MAX_SEARCH_RESULTS}",
            )

        escaped_query = (
            query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
        sql = (
            "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
            "FROM emails WHERE (sender LIKE ? ESCAPE '\\' OR recipient LIKE ? ESCAPE '\\' "
            "OR subject LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')"
        )
        parameters: list[object] = [pattern, pattern, pattern, pattern]
        if recipient is not None:
            sql += " AND lower(recipient) = lower(?)"
            parameters.append(normalized_recipient)
        sql += " ORDER BY timestamp DESC, email_id DESC LIMIT ?"
        parameters.append(limit)

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(sql, parameters).fetchall()
            return self._success(action, tuple(self._record(row) for row in rows))
        except sqlite3.Error:
            LOGGER.exception("email_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local email database is unavailable"
            )

    def send_email(self, recipient: str, subject: str, body: str) -> EmailToolResult:
        """Store a new unread email from the local agent sender."""
        action = "send_email"
        LOGGER.info("email_tool.%s invoked", action)
        normalized_recipient = self._normalize_email(recipient)
        if normalized_recipient is None:
            return self._failure(
                action, "invalid_input", "recipient must be a valid email address"
            )
        if not isinstance(subject, str) or not subject.strip():
            return self._failure(action, "invalid_input", "subject is required")
        if (
            len(subject.strip()) > MAX_SUBJECT_LENGTH
            or "\n" in subject
            or "\r" in subject
        ):
            return self._failure(
                action, "invalid_input", "subject is too long or contains a line break"
            )
        if not isinstance(body, str) or not body.strip():
            return self._failure(action, "invalid_input", "body is required")
        if len(body) > MAX_BODY_LENGTH:
            return self._failure(
                action,
                "invalid_input",
                f"body must be at most {MAX_BODY_LENGTH} characters",
            )

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "INSERT INTO emails (sender, recipient, subject, body, timestamp, read_status) "
                    "VALUES (?, ?, ?, ?, ?, 'unread')",
                    (
                        DEFAULT_SENDER,
                        normalized_recipient,
                        subject.strip(),
                        body.strip(),
                        timestamp,
                    ),
                )
                row = connection.execute(
                    "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
                    "FROM emails WHERE email_id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
            return self._success(action, (self._record(row),))
        except sqlite3.Error:
            LOGGER.exception("email_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local email database is unavailable"
            )

    def list_student_emails(self, student_id: int, folder: str) -> EmailToolResult:
        """List messages addressed to or sent by one student."""
        action = "list_student_emails"
        LOGGER.info("email_tool.%s invoked", action)
        if (
            isinstance(student_id, bool)
            or not isinstance(student_id, int)
            or student_id < 1
        ):
            return self._failure(
                action, "invalid_input", "student_id must be a positive integer"
            )
        if folder not in {"inbox", "sent"}:
            return self._failure(
                action, "invalid_input", "folder must be 'inbox' or 'sent'"
            )

        address_column = "recipient" if folder == "inbox" else "sender"
        try:
            with closing(self._connect()) as connection:
                student = connection.execute(
                    "SELECT email FROM students WHERE student_id = ?", (student_id,)
                ).fetchone()
                if student is None:
                    return self._failure(
                        action, "not_found", "No student exists with that student_id"
                    )
                rows = connection.execute(
                    "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
                    f"FROM emails WHERE lower({address_column}) LIKE lower(?) "
                    "ORDER BY timestamp DESC, email_id DESC LIMIT ?",
                    (f"%{student['email']}%", MAX_SEARCH_RESULTS),
                ).fetchall()
            return self._success(action, tuple(self._record(row) for row in rows))
        except sqlite3.Error:
            LOGGER.exception("email_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local email database is unavailable"
            )

    def read_student_email(self, student_id: int, email_id: int) -> EmailToolResult:
        """Read a message only if it belongs to the requested student's mailbox."""
        action = "read_student_email"
        LOGGER.info("email_tool.%s invoked", action)
        if (
            isinstance(student_id, bool)
            or not isinstance(student_id, int)
            or student_id < 1
        ):
            return self._failure(
                action, "invalid_input", "student_id must be a positive integer"
            )
        if isinstance(email_id, bool) or not isinstance(email_id, int) or email_id < 1:
            return self._failure(
                action, "invalid_input", "email_id must be a positive integer"
            )

        try:
            with closing(self._connect()) as connection, connection:
                student = connection.execute(
                    "SELECT email FROM students WHERE student_id = ?", (student_id,)
                ).fetchone()
                if student is None:
                    return self._failure(
                        action, "not_found", "No student exists with that student_id"
                    )
                address_pattern = f"%{student['email']}%"
                row = connection.execute(
                    "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
                    "FROM emails WHERE email_id = ? "
                    "AND (lower(sender) LIKE lower(?) OR lower(recipient) LIKE lower(?))",
                    (email_id, address_pattern, address_pattern),
                ).fetchone()
                if row is None:
                    return self._failure(
                        action, "not_found", "No matching email exists in this mailbox"
                    )
                connection.execute(
                    "UPDATE emails SET read_status = 'read' WHERE email_id = ?",
                    (email_id,),
                )
                row = connection.execute(
                    "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
                    "FROM emails WHERE email_id = ?",
                    (email_id,),
                ).fetchone()
            return self._success(action, (self._record(row),))
        except sqlite3.Error:
            LOGGER.exception("email_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local email database is unavailable"
            )

    def submit_student_email(
        self, student_id: int, subject: str, body: str
    ) -> EmailToolResult:
        """Store a student's message to the fictional local university inbox."""
        action = "submit_student_email"
        LOGGER.info("email_tool.%s invoked", action)
        if (
            isinstance(student_id, bool)
            or not isinstance(student_id, int)
            or student_id < 1
        ):
            return self._failure(
                action, "invalid_input", "student_id must be a positive integer"
            )
        if not isinstance(subject, str) or not subject.strip():
            return self._failure(action, "invalid_input", "subject is required")
        if (
            len(subject.strip()) > MAX_SUBJECT_LENGTH
            or "\n" in subject
            or "\r" in subject
        ):
            return self._failure(
                action, "invalid_input", "subject is too long or contains a line break"
            )
        if not isinstance(body, str) or not body.strip():
            return self._failure(action, "invalid_input", "body is required")
        if len(body) > MAX_BODY_LENGTH:
            return self._failure(
                action,
                "invalid_input",
                f"body must be at most {MAX_BODY_LENGTH} characters",
            )

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            with closing(self._connect()) as connection, connection:
                student = connection.execute(
                    "SELECT first_name, last_name, email, status "
                    "FROM students WHERE student_id = ?",
                    (student_id,),
                ).fetchone()
                if student is None:
                    return self._failure(
                        action, "not_found", "No student exists with that student_id"
                    )
                if student["status"].casefold() != "active":
                    return self._failure(
                        action, "not_eligible", "Only active students can send messages"
                    )
                sender = (
                    f"{student['first_name']} {student['last_name']} "
                    f"<{student['email']}>"
                )
                cursor = connection.execute(
                    "INSERT INTO emails (sender, recipient, subject, body, timestamp, read_status) "
                    "VALUES (?, ?, ?, ?, ?, 'unread')",
                    (
                        sender,
                        STUDENT_INBOX_ADDRESS,
                        subject.strip(),
                        body.strip(),
                        timestamp,
                    ),
                )
                row = connection.execute(
                    "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
                    "FROM emails WHERE email_id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
            return self._success(action, (self._record(row),))
        except sqlite3.Error:
            LOGGER.exception("email_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local email database is unavailable"
            )

    def list_emails_by_recipient(
        self, recipient: str, limit: int = MAX_SEARCH_RESULTS
    ) -> EmailToolResult:
        """List all messages sent to one recipient address."""
        action = "list_emails_by_recipient"

        normalized_recipient = self._normalize_email(recipient)
        if normalized_recipient is None:
            return self._failure(
                action,
                "invalid_input",
                "recipient must be a valid email address",
            )

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT email_id, sender, recipient, subject, body, timestamp, read_status "
                    "FROM emails "
                    "WHERE lower(recipient) = lower(?) "
                    "ORDER BY timestamp DESC, email_id DESC "
                    "LIMIT ?",
                    (normalized_recipient, limit),
                ).fetchall()

            return self._success(
                action,
                tuple(self._record(row) for row in rows),
            )

        except sqlite3.Error:
            LOGGER.exception("email_tool.%s encountered a database error", action)
            return self._failure(
                action,
                "database_error",
                "The local email database is unavailable",
            )

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise sqlite3.OperationalError("database file does not exist")
        connection = sqlite3.connect(
            self.database_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _normalize_email(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        addresses = getaddresses([value.strip()])
        if len(addresses) != 1:
            return None
        address = addresses[0][1].strip()
        if not EMAIL_PATTERN.fullmatch(address):
            return None
        return address

    @classmethod
    def _valid_email(cls, value: object) -> bool:
        return cls._normalize_email(value) is not None

    @staticmethod
    def _record(row: sqlite3.Row) -> EmailRecord:
        return EmailRecord(
            email_id=row["email_id"],
            sender=row["sender"],
            recipient=row["recipient"],
            subject=row["subject"],
            body=row["body"],
            timestamp=row["timestamp"],
            read_status=row["read_status"],
        )

    @staticmethod
    def _success(action: str, emails: tuple[EmailRecord, ...]) -> EmailToolResult:
        LOGGER.info("email_tool.%s completed successfully", action)
        return EmailToolResult(success=True, action=action, emails=emails)

    @staticmethod
    def _failure(action: str, error_code: str, error: str) -> EmailToolResult:
        LOGGER.warning("email_tool.%s failed: %s", action, error_code)
        return EmailToolResult(
            success=False,
            action=action,
            error_code=error_code,
            error=error,
        )
