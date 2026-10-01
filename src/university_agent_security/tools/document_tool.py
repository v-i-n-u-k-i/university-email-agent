"""Local policy document search tool for the Westbridge University agent."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .. import document_search

LOGGER = logging.getLogger(__name__)
MAX_QUERY_LENGTH = 300
MAX_RESULTS = 20


@dataclass(frozen=True)
class DocumentToolResult:
    """Structured result containing the most relevant matching sections."""

    success: bool
    action: str
    sections: tuple[document_search.PolicySectionMatch, ...] = ()
    error_code: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "action": self.action,
            "sections": [section.to_dict() for section in self.sections],
            "error_code": self.error_code,
            "error": self.error,
        }


class DocumentTool:
    """Search local Markdown policy sections without external services."""

    def __init__(
        self, policy_dir: str | Path = document_search.POLICY_DIRECTORY
    ) -> None:
        self.policy_dir = Path(policy_dir).resolve()

    def search_documents(self, query: str, limit: int = 5) -> DocumentToolResult:
        """Return policy sections ranked by matching query terms."""
        action = "search_documents"
        LOGGER.info("document_tool.%s invoked", action)
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > MAX_QUERY_LENGTH
            or not re.search(r"[a-zA-Z0-9]", query)
        ):
            return self._failure(
                action,
                "invalid_input",
                f"query must contain searchable text of at most {MAX_QUERY_LENGTH} characters",
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            return self._failure(
                action,
                "invalid_input",
                f"limit must be an integer from 1 to {MAX_RESULTS}",
            )

        try:
            sections = document_search.search_policy_sections(
                query.strip(), self.policy_dir, limit
            )
            return self._success(action, tuple(sections))
        except (OSError, UnicodeError):
            LOGGER.exception("document_tool.%s could not read local policy documents", action)
            return self._failure(
                action, "document_read_error", "Local policy documents could not be read"
            )

    @staticmethod
    def _success(
        action: str, sections: tuple[document_search.PolicySectionMatch, ...]
    ) -> DocumentToolResult:
        LOGGER.info("document_tool.%s completed successfully", action)
        return DocumentToolResult(success=True, action=action, sections=sections)

    @staticmethod
    def _failure(action: str, error_code: str, error: str) -> DocumentToolResult:
        LOGGER.warning("document_tool.%s failed: %s", action, error_code)
        return DocumentToolResult(
            success=False,
            action=action,
            error_code=error_code,
            error=error,
        )