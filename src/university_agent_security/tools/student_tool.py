"""Validated, limited student lookups for the Westbridge University agent."""

import logging
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[3] / "data" / "university.db"
SQLITE_BUSY_TIMEOUT_SECONDS = 30
UNIT_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")


@dataclass(frozen=True)
class StudentToolResult:
    """A structured result containing only fields for the requested operation."""

    success: bool
    action: str
    data: dict[str, int | str | bool] | None = None
    error_code: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "action": self.action,
            "data": self.data,
            "error_code": self.error_code,
            "error": self.error,
        }


class StudentTool:
    """Look up students and check their unit enrollment in local SQLite."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path).resolve()

    def lookup_student(self, student_id: int) -> StudentToolResult:
        """Return the requested student's profile fields only."""
        action = "lookup_student"
        LOGGER.info("student_tool.%s invoked", action)
        if not self._valid_student_id(student_id):
            return self._failure(
                action, "invalid_input", "student_id must be a positive integer"
            )

        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT student_id, first_name, last_name, email, course, status "
                    "FROM students WHERE student_id = ?",
                    (student_id,),
                ).fetchone()
            if row is None:
                return self._failure(
                    action, "not_found", "No student exists with that student_id"
                )
            data = {
                "student_id": row["student_id"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "email": row["email"],
                "course": row["course"],
                "status": row["status"],
            }
            return self._success(action, data)
        except sqlite3.Error:
            LOGGER.exception("student_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local student database is unavailable"
            )

    def check_enrollment(self, student_id: int, unit_code: str) -> StudentToolResult:
        """Return whether a student is currently enrolled in the requested unit."""
        action = "check_enrollment"
        LOGGER.info("student_tool.%s invoked", action)
        normalized_unit_code = self._normalize_unit_code(unit_code)
        input_error = self._validate_student_and_unit(student_id, normalized_unit_code)
        if input_error is not None:
            return self._failure(action, "invalid_input", input_error)

        try:
            row = self._student_unit_row(student_id, normalized_unit_code)
            if row is None:
                return self._failure(
                    action, "not_found", "No student exists with that student_id"
                )
            data = {
                "student_id": student_id,
                "unit_code": normalized_unit_code,
                "is_enrolled": (row["enrollment_status"] or "").casefold()
                == "enrolled",
            }
            return self._success(action, data)
        except sqlite3.Error:
            LOGGER.exception("student_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local student database is unavailable"
            )

    def check_withdrawal_eligibility(
        self, student_id: int, unit_code: str
    ) -> StudentToolResult:
        """Check active status and current enrollment, not deadlines or approval."""
        action = "check_withdrawal_eligibility"
        LOGGER.info("student_tool.%s invoked", action)
        normalized_unit_code = self._normalize_unit_code(unit_code)
        input_error = self._validate_student_and_unit(student_id, normalized_unit_code)
        if input_error is not None:
            return self._failure(action, "invalid_input", input_error)

        try:
            row = self._student_unit_row(student_id, normalized_unit_code)
            if row is None:
                return self._failure(
                    action, "not_found", "No student exists with that student_id"
                )

            is_active = row["student_status"].casefold() == "active"
            is_enrolled = (row["enrollment_status"] or "").casefold() == "enrolled"
            data: dict[str, int | str | bool] = {
                "student_id": student_id,
                "unit_code": normalized_unit_code,
                "eligible": is_active and is_enrolled,
                "eligibility_basis": (
                    "active status and current enrollment only; withdrawal deadlines "
                    "and exception review are not evaluated"
                ),
            }
            return self._success(action, data)
        except sqlite3.Error:
            LOGGER.exception("student_tool.%s encountered a database error", action)
            return self._failure(
                action, "database_error", "The local student database is unavailable"
            )

    def _student_unit_row(self, student_id: int, unit_code: str) -> sqlite3.Row | None:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT s.status AS student_status, e.enrollment_status "
                "FROM students AS s "
                "LEFT JOIN enrollments AS e "
                "ON e.student_id = s.student_id AND e.unit_code = ? "
                "WHERE s.student_id = ?",
                (unit_code, student_id),
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise sqlite3.OperationalError("database file does not exist")
        connection = sqlite3.connect(
            self.database_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _valid_student_id(student_id: object) -> bool:
        return (
            not isinstance(student_id, bool)
            and isinstance(student_id, int)
            and student_id > 0
        )

    @staticmethod
    def _normalize_unit_code(unit_code: object) -> str | None:
        if not isinstance(unit_code, str):
            return None
        normalized = unit_code.strip().upper()
        if not UNIT_CODE_PATTERN.fullmatch(normalized):
            return None
        return normalized

    @classmethod
    def _validate_student_and_unit(
        cls, student_id: object, unit_code: str | None
    ) -> str | None:
        if not cls._valid_student_id(student_id):
            return "student_id must be a positive integer"
        if unit_code is None:
            return "unit_code must contain 1 to 32 letters, numbers, underscores, or hyphens"
        return None

    @staticmethod
    def _success(action: str, data: dict[str, int | str | bool]) -> StudentToolResult:
        LOGGER.info("student_tool.%s completed successfully", action)
        return StudentToolResult(success=True, action=action, data=data)

    @staticmethod
    def _failure(action: str, error_code: str, error: str) -> StudentToolResult:
        LOGGER.warning("student_tool.%s failed: %s", action, error_code)
        return StudentToolResult(
            success=False,
            action=action,
            error_code=error_code,
            error=error,
        )
