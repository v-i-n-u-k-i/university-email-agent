"""Keyword search for local Westbridge University policy documents."""

import re
from dataclasses import dataclass
from pathlib import Path

POLICY_DIRECTORY = Path(__file__).resolve().parents[2] / "policies"


def _terms(text: str) -> list[str]:
    terms = re.findall(r"[a-z0-9]+", text.casefold())
    normalized = []
    for term in terms:
        if term.endswith("ies") and len(term) > 4:
            term = f"{term[:-3]}y"
        elif term.endswith("s") and not term.endswith(("ss", "us")) and len(term) > 3:
            term = term[:-1]
        normalized.append(term)
    return normalized


@dataclass(frozen=True)
class PolicyMatch:
    """A policy line containing the requested keyword."""

    filename: str
    line_number: int
    text: str


@dataclass(frozen=True)
class PolicySectionMatch:
    """A ranked Markdown policy section matching a search query."""

    filename: str
    document_title: str
    section_title: str
    text: str
    relevance: float

    def to_dict(self) -> dict[str, str | float]:
        return {
            "filename": self.filename,
            "document_title": self.document_title,
            "section_title": self.section_title,
            "text": self.text,
            "relevance": self.relevance,
        }


def search_policies(
    keyword: str, policy_dir: str | Path = POLICY_DIRECTORY
) -> list[PolicyMatch]:
    """Return policy lines containing a case-insensitive keyword substring."""
    normalized_keyword = keyword.strip().casefold()
    if not normalized_keyword:
        return []

    matches = []
    for path in sorted(Path(policy_dir).glob("*_policy.md")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if normalized_keyword in line.casefold():
                matches.append(PolicyMatch(path.name, line_number, line.strip()))

    return matches


def search_policy_sections(
    query: str,
    policy_dir: str | Path = POLICY_DIRECTORY,
    limit: int = 5,
) -> list[PolicySectionMatch]:
    """Find local policy sections and rank them by query-term coverage."""
    query_terms = tuple(dict.fromkeys(_terms(query)))
    if not query_terms or limit < 1:
        return []

    ranked_matches: list[tuple[float, int, int, PolicySectionMatch]] = []
    for path in sorted(Path(policy_dir).glob("*_policy.md")):
        document_title = path.stem.replace("_", " ").title()
        section_title: str | None = None
        section_lines: list[str] = []
        document_lines: list[str] = []
        sections: list[tuple[str, str]] = []

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                document_title = line[2:].strip()
            elif line.startswith("## "):
                if section_title is not None:
                    sections.append((section_title, "\n".join(section_lines).strip()))
                section_title = line[3:].strip()
                section_lines = []
            elif section_title is not None:
                section_lines.append(line)
            else:
                document_lines.append(line)

        if section_title is not None:
            sections.append((section_title, "\n".join(section_lines).strip()))
        elif document_lines:
            sections.append((document_title, "\n".join(document_lines).strip()))

        for title, text in sections:
            title_terms = set(_terms(f"{document_title} {title}"))
            content_terms = _terms(text)
            content_term_set = set(content_terms)
            matched_terms = [
                term for term in query_terms if term in title_terms or term in content_term_set
            ]
            if not matched_terms:
                continue

            relevance = len(matched_terms) / len(query_terms)
            title_hits = sum(term in title_terms for term in matched_terms)
            frequency = sum(content_terms.count(term) for term in matched_terms)
            result = PolicySectionMatch(
                filename=path.name,
                document_title=document_title,
                section_title=title,
                text=text,
                relevance=relevance,
            )
            ranked_matches.append((relevance, title_hits, frequency, result))

    ranked_matches.sort(
        key=lambda match: (
            -match[0],
            -match[1],
            -match[2],
            match[3].filename.casefold(),
            match[3].section_title.casefold(),
        )
    )
    return [match[3] for match in ranked_matches[:limit]]
