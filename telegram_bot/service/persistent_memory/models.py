"""Domain models for the persistent memory system.

This module defines immutable value objects and aggregates for managing
structured, long-term facts in the Obsidian knowledge base:

- PersistentFact: Immutable fact with metadata (confidence, dates, sources)
- PersistentMemorySection: Collection of facts scoped to a domain (e.g., "Health")

Facts are stored in Markdown tables with deterministic parsing/rendering.
The merge operation enables intelligent fact updates across consolidation runs.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import ClassVar


def _parse_optional_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _format_optional_date(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    return float(text)


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    formatted = f"{value:.4f}".rstrip("0").rstrip(".")
    return formatted


def _parse_sources(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    items = [item.strip() for item in raw.split(";")]
    return tuple(item for item in items if item)


def _format_sources(sources: Sequence[str]) -> str:
    return "; ".join(sources)


@dataclass(frozen=True, slots=True)
class PersistentFact:
    """Immutable representation of a persistent fact stored in Markdown tables."""

    id: str
    statement: str
    category: str
    confidence: float | None = None
    first_seen: date | None = None
    last_seen: date | None = None
    sources: Sequence[str] = field(default_factory=tuple)
    status: str | None = None
    notes: str | None = None

    @classmethod
    def from_table_row(cls, row: dict[str, str]) -> PersistentFact:
        """Create a fact from a Markdown table row mapping."""
        return cls(
            id=row.get("id", "").strip(),
            statement=row.get("statement", "").strip(),
            category=row.get("category", "").strip(),
            confidence=_parse_optional_float(row.get("confidence")),
            first_seen=_parse_optional_date(row.get("first_seen")),
            last_seen=_parse_optional_date(row.get("last_seen")),
            sources=_parse_sources(row.get("sources")),
            status=row.get("status", "").strip() or None,
            notes=row.get("notes", "").strip() or None,
        )

    @classmethod
    def from_llm_payload(
        cls,
        id: str,
        statement: str,
        category: str,
        confidence: float | None = None,
        first_seen: str | None = None,
        last_seen: str | None = None,
        sources: Sequence[str] = (),
        status: str | None = None,
        notes: str | None = None,
    ) -> PersistentFact:
        """Create a fact directly from LLM payload without string conversion.

        This method avoids the overhead of converting typed values to strings
        and back, providing better performance for LLM-generated facts.
        """
        return cls(
            id=id.strip(),
            statement=statement.strip(),
            category=category.strip(),
            confidence=confidence,
            first_seen=_parse_optional_date(first_seen),
            last_seen=_parse_optional_date(last_seen),
            sources=tuple(sources),
            status=status.strip() if status else None,
            notes=notes.strip() if notes else None,
        )

    def to_table_row(self) -> dict[str, str]:
        """Render the fact into a Markdown table row mapping."""
        return {
            "id": self.id,
            "statement": self.statement,
            "category": self.category,
            "confidence": _format_optional_float(self.confidence),
            "first_seen": _format_optional_date(self.first_seen),
            "last_seen": _format_optional_date(self.last_seen),
            "sources": _format_sources(self.sources),
            "status": (self.status or ""),
            "notes": (self.notes or ""),
        }

    def merge(self, other: PersistentFact) -> PersistentFact:
        """Merge two facts referring to the same statement.

        Precedence rules:
        - statement, category, status, notes: prefer values from `other` when present
        - confidence: use `other.confidence`, fallback to `self.confidence`
        - first_seen: earliest date between both facts
        - last_seen: latest date between both facts
        - sources: combined and deduplicated from both facts
        - id: use existing ID or accept `other.id`

        Raises:
            ValueError: If both facts have different non-empty IDs
        """
        if self.id and other.id and self.id != other.id:
            raise ValueError("Cannot merge facts with different identifiers")

        first_seen_candidates = [value for value in (self.first_seen, other.first_seen) if value is not None]
        last_seen_candidates = [value for value in (self.last_seen, other.last_seen) if value is not None]

        # Deduplicate sources while preserving order using dict
        seen: dict[str, None] = {}
        for source in (*self.sources, *other.sources):
            seen[source] = None
        combined_sources = list(seen.keys())

        merged = replace(
            other,
            id=self.id or other.id,
            statement=other.statement or self.statement,
            category=other.category or self.category,
            first_seen=min(first_seen_candidates) if first_seen_candidates else None,
            last_seen=max(last_seen_candidates) if last_seen_candidates else None,
            sources=tuple(combined_sources),
            status=other.status or self.status,
            notes=other.notes or self.notes,
        )

        if merged.confidence is None:
            merged = replace(merged, confidence=self.confidence)

        return merged


@dataclass(slots=True)
class PersistentMemorySection:
    """Collection of facts scoped to a single persistent memory domain section."""

    name: str
    facts: list[PersistentFact]

    TABLE_HEADERS: ClassVar[tuple[str, ...]] = (
        "id",
        "statement",
        "category",
        "confidence",
        "first_seen",
        "last_seen",
        "sources",
        "status",
        "notes",
    )

    @staticmethod
    def _split_row(line: str) -> list[str]:
        stripped = line.strip()
        if not stripped:
            return []
        if not stripped.startswith("|"):
            raise ValueError("Expected Markdown table row to start with '|'")
        parts = stripped.split("|")
        if len(parts) <= 2:
            return []
        data_cells = parts[1:-1]
        return [cell.strip() for cell in data_cells]

    @staticmethod
    def _is_separator_cell(cell: str) -> bool:
        """Return True when the cell matches Markdown separator syntax."""
        if not cell:
            return False
        normalized = cell.replace("-", "").replace(":", "").strip()
        return normalized == ""

    @staticmethod
    def _trim_trailing_cells(cells: list[str], expected_width: int, *, removable: Callable[[str], bool]) -> list[str]:
        """Remove formatter-added trailing columns while keeping required blanks."""
        while len(cells) > expected_width and removable(cells[-1]):
            cells = cells[:-1]
        return cells

    @classmethod
    def parse(cls, section_name: str, markdown: str) -> PersistentMemorySection:
        """Parse a Markdown section body into structured facts."""
        text = markdown.strip()
        if not text:
            return cls(section_name, [])

        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError(f"Section '{section_name}' is missing table structure")

        header_cells = cls._trim_trailing_cells(
            cls._split_row(lines[0]), len(cls.TABLE_HEADERS), removable=lambda cell: not cell
        )
        if tuple(header_cells) != cls.TABLE_HEADERS:
            raise ValueError(f"Unexpected table headers in section '{section_name}'")

        separator_cells = cls._trim_trailing_cells(
            cls._split_row(lines[1]),
            len(cls.TABLE_HEADERS),
            removable=cls._is_separator_cell,
        )
        if len(separator_cells) != len(cls.TABLE_HEADERS) or any(
            not cls._is_separator_cell(cell) for cell in separator_cells
        ):
            raise ValueError(f"Malformed table separator in section '{section_name}'")

        facts: list[PersistentFact] = []
        for line in lines[2:]:
            if not line.strip():
                continue
            row_cells = cls._trim_trailing_cells(
                cls._split_row(line), len(cls.TABLE_HEADERS), removable=lambda cell: not cell
            )
            if len(row_cells) != len(cls.TABLE_HEADERS):
                raise ValueError(f"Row in section '{section_name}' has incorrect column count")
            row_mapping = dict(zip(cls.TABLE_HEADERS, row_cells))
            facts.append(PersistentFact.from_table_row(row_mapping))

        return cls(section_name, facts)

    @staticmethod
    def _join_row(cells: Iterable[str]) -> str:
        joined = " | ".join(cells).rstrip()
        return f"| {joined} |"

    def render(self) -> str:
        """Render the section into a Markdown table including headers."""
        rows = [
            self._join_row(self.TABLE_HEADERS),
            self._join_row(["---"] * len(self.TABLE_HEADERS)),
        ]
        for fact in self.facts:
            row_mapping = fact.to_table_row()
            cells = [row_mapping[header] for header in self.TABLE_HEADERS]
            rows.append(self._join_row(cells))
        return "\n".join(rows)

    def diff(
        self,
        additions: Iterable[PersistentFact],
        updates: Iterable[PersistentFact],
        removals: Iterable[str],
    ) -> PersistentMemorySection:
        """Return a new section after applying the provided changes."""
        index = {fact.id: fact for fact in self.facts}
        order = [fact.id for fact in self.facts]

        for removal_id in removals:
            if removal_id in index:
                del index[removal_id]
                order = [existing_id for existing_id in order if existing_id != removal_id]

        for updated in updates:
            if not updated.id:
                raise ValueError("Updated facts must have identifiers")
            index[updated.id] = updated
            if updated.id not in order:
                order.append(updated.id)

        for addition in additions:
            if not addition.id:
                raise ValueError("Added facts must have identifiers")
            index[addition.id] = addition
            if addition.id not in order:
                order.append(addition.id)

        new_facts = [index[fact_id] for fact_id in order if fact_id in index]
        return PersistentMemorySection(self.name, new_facts)
