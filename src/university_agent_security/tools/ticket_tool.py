"""Validated local support-ticket operations for the Westbridge University agent."""

import logging
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

LOGGER = logging.getLogger(__name__)
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[3] / "data" / "university.db"
ALLOWED_STATUSES = frozenset({"open", "in_progress", "resolved"})
MAX_SUBJECT_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10_000
SQLITE_BUSY_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class TicketRecord:
    """A ticket row returned by the tool."""

    ticket_id: int
    student_id: int
    subject: str
    description: str
    status: str
    created_at: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class TicketToolResult:
    """Structured result shared by all public ticket operations."""

    success: bool
    action: str
    ticket: TicketRecord | None = None
    error_code: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "action": self.action,
            "ticket": self.ticket.to_dict() if self.ticket else None,
            "error_code": self.error_code,
            "error": self.error,
        }


class TicketTool:
    """Create and manage student support tickets in the local SQLite database."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path).resolve()

    def create_ticket(
        self, student_id: int, subject: str, description: str
    ) -> TicketToolResult:
        """Create an open ticket for an existing student."""
        action = "create_ticket"
        LOGGER.info("ticket_tool.%s invoked", action)

        input_error = self._validate_student_id(student_id)
        if input_error is not None:
            return self._failure(action, "invalid_input", input_error)
        normalized_subject, input_error = self._normalize_text(
            subject, MAX_SUBJECT_LENGTH, "subject", single_line=True
        )
        if input_error is not None:
            return self._failure(action, "invalid_input", input_error)
        normalized_description, input_error = self._normalize_text(
            description, MAX_DESCRIPTION_LENGTH, "description"
        )
        if input_error is not None:
            return self._failure(action, "invalid_input", input_error)

        try:
            with closing(self._connect()) as connection, connection:
                student = connection.execute(
                    "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
                ).fetchone()
                if student is None:
                    return self._failure(
                        action, "not_found", "No student exists with that student_id"
                    )
                cursor = connection.execute(
                    "INSERT INTO tickets (student_id, subject, description, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        student_id,
                        normalized_subject,
                        normalized_description,
                        "open",
                        datetime.now(UTC).isoformat(timespec="seconds"),
                    ),
                )
                row = connection.execute(
                    "SELECT ticket_id, student_id, subject, description, status, created_at "
                    "FROM tickets WHERE ticket_id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
            return self._success(action, self._record(row))
        except sqlite3.Error:
            LOGGER.exception("ticket_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local ticket database is unavailable"
            )

    def get_ticket(self, ticket_id: int) -> TicketToolResult:
        """Return one ticket by its ID."""
        action = "get_ticket"
        LOGGER.info("ticket_tool.%s invoked", action)
        input_error = self._validate_id(ticket_id, "ticket_id")
        if input_error is not None:
            return self._failure(action, "invalid_input", input_error)

        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT ticket_id, student_id, subject, description, status, created_at "
                    "FROM tickets WHERE ticket_id = ?",
                    (ticket_id,),
                ).fetchone()
            if row is None:
                return self._failure(
                    action, "not_found", "No ticket exists with that ticket_id"
                )
            return self._success(action, self._record(row))
        except sqlite3.Error:
            LOGGER.exception("ticket_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local ticket database is unavailable"
            )

    def update_ticket_status(self, ticket_id: int, status: str) -> TicketToolResult:
        """Update a ticket to one of the supported statuses."""
        action = "update_ticket_status"
        LOGGER.info("ticket_tool.%s invoked", action)
        input_error = self._validate_id(ticket_id, "ticket_id")
        if input_error is not None:
            return self._failure(action, "invalid_input", input_error)
        normalized_status = self._normalize_status(status)
        if normalized_status is None:
            choices = ", ".join(sorted(ALLOWED_STATUSES))
            return self._failure(
                action,
                "invalid_input",
                f"status must be one of: {choices}",
            )

        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "UPDATE tickets SET status = ? WHERE ticket_id = ?",
                    (normalized_status, ticket_id),
                )
                if cursor.rowcount == 0:
                    return self._failure(
                        action, "not_found", "No ticket exists with that ticket_id"
                    )
                row = connection.execute(
                    "SELECT ticket_id, student_id, subject, description, status, created_at "
                    "FROM tickets WHERE ticket_id = ?",
                    (ticket_id,),
                ).fetchone()
            return self._success(action, self._record(row))
        except sqlite3.Error:
            LOGGER.exception("ticket_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local ticket database is unavailable"
            )

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise sqlite3.OperationalError("database file does not exist")
        connection = sqlite3.connect(
            self.database_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _validate_id(value: object, name: str) -> str | None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return f"{name} must be a positive integer"
        return None

    @classmethod
    def _validate_student_id(cls, student_id: object) -> str | None:
        return cls._validate_id(student_id, "student_id")

    @staticmethod
    def _normalize_text(
        value: object,
        maximum_length: int,
        name: str,
        *,
        single_line: bool = False,
    ) -> tuple[str | None, str | None]:
        if not isinstance(value, str) or not value.strip():
            return None, f"{name} is required"
        normalized = value.strip()
        if len(normalized) > maximum_length:
            return None, f"{name} must be at most {maximum_length} characters"
        if single_line and ("\n" in normalized or "\r" in normalized):
            return None, f"{name} cannot contain line breaks"
        return normalized, None

    @staticmethod
    def _normalize_status(status: object) -> str | None:
        if not isinstance(status, str):
            return None
        normalized = status.strip().casefold()
        if normalized not in ALLOWED_STATUSES:
            return None
        return normalized

    @staticmethod
    def _record(row: sqlite3.Row) -> TicketRecord:
        return TicketRecord(
            ticket_id=row["ticket_id"],
            student_id=row["student_id"],
            subject=row["subject"],
            description=row["description"],
            status=row["status"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _success(action: str, ticket: TicketRecord) -> TicketToolResult:
        LOGGER.info("ticket_tool.%s completed successfully", action)
        return TicketToolResult(success=True, action=action, ticket=ticket)

    @staticmethod
    def _failure(action: str, error_code: str, error: str) -> TicketToolResult:
        LOGGER.warning("ticket_tool.%s failed: %s", action, error_code)
        return TicketToolResult(
            success=False,
            action=action,
            error_code=error_code,
            error=error,
        )
