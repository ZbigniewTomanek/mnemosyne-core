from __future__ import annotations

from datetime import date

import pytest

from telegram_bot.service.persistent_memory.models import PersistentFact, PersistentMemorySection


def test_fact_table_row_conversion_roundtrip() -> None:
    row = {
        "id": "fact-1",
        "statement": "Prefers tea over coffee",
        "category": "preference",
        "confidence": "0.85",
        "first_seen": "2024-01-10",
        "last_seen": "2024-02-05",
        "sources": "note-2024-01-10; note-2024-02-05",
        "status": "active",
        "notes": "Updated after January review",
    }

    fact = PersistentFact.from_table_row(row)

    assert fact.confidence == 0.85
    assert fact.first_seen == date(2024, 1, 10)
    assert fact.sources == ("note-2024-01-10", "note-2024-02-05")

    rendered = fact.to_table_row()
    assert rendered == {
        "id": "fact-1",
        "statement": "Prefers tea over coffee",
        "category": "preference",
        "confidence": "0.85",
        "first_seen": "2024-01-10",
        "last_seen": "2024-02-05",
        "sources": "note-2024-01-10; note-2024-02-05",
        "status": "active",
        "notes": "Updated after January review",
    }


def test_fact_merge_prefers_latest_metadata() -> None:
    original = PersistentFact(
        id="fact-1",
        statement="Enjoys morning runs",
        category="health",
        confidence=0.6,
        first_seen=date(2024, 1, 1),
        last_seen=date(2024, 1, 2),
        sources=("journal-2024-01-01",),
        status="active",
        notes=None,
    )
    incoming = PersistentFact(
        id="fact-1",
        statement="Enjoys morning runs",
        category="health",
        confidence=0.9,
        first_seen=date(2024, 1, 5),
        last_seen=date(2024, 2, 1),
        sources=("journal-2024-02-01",),
        status="reinforced",
        notes="Consistent across February entries",
    )

    merged = original.merge(incoming)

    assert merged.first_seen == date(2024, 1, 1)
    assert merged.last_seen == date(2024, 2, 1)
    assert merged.confidence == 0.9
    assert merged.sources == ("journal-2024-01-01", "journal-2024-02-01")
    assert merged.status == "reinforced"
    assert merged.notes == "Consistent across February entries"


def test_section_parse_accepts_extended_markdown_separators() -> None:
    markdown = """
| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |
| :----- | -----: | :-: | :---- | ---- | ---- | :---: | --- | --- |
| fact-1 | Prefers tea | preference | 0.85 | 2024-01-10 | 2024-02-05 | note-a; note-b | active | Updated after review |
""".strip()

    section = PersistentMemorySection.parse("Preferencje", markdown)

    assert section.name == "Preferencje"
    assert len(section.facts) == 1
    assert section.facts[0].statement == "Prefers tea"
    assert section.facts[0].sources == ("note-a", "note-b")


def test_section_parse_ignores_trailing_blank_columns() -> None:
    markdown = """
| id | statement | category | confidence | first_seen | last_seen | sources | status | notes | |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fact-1 | Value | category | | | | | active | | |
""".strip()

    section = PersistentMemorySection.parse("Preferencje", markdown)

    assert len(section.facts) == 1
    assert section.facts[0].status == "active"


def test_section_parse_rejects_invalid_separator_cells() -> None:
    markdown = """
| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |
| --- | XXX | --- | --- | --- | --- | --- | --- | --- |
| fact-1 | Invalid separator | category | | | | | | |
""".strip()

    with pytest.raises(ValueError) as exc:
        PersistentMemorySection.parse("Błędne", markdown)

    assert "Malformed table separator" in str(exc.value)


def test_section_diff_applies_add_update_remove() -> None:
    fact_a = PersistentFact(
        id="fact-a",
        statement="Uses GTD system",
        category="productivity",
        confidence=0.8,
        first_seen=date(2024, 1, 1),
        last_seen=date(2024, 1, 1),
        sources=("daily-2024-01-01",),
        status="active",
        notes=None,
    )
    fact_b = PersistentFact(
        id="fact-b",
        statement="Reviews tasks every Sunday",
        category="productivity",
        confidence=0.7,
        first_seen=date(2024, 1, 2),
        last_seen=date(2024, 1, 2),
        sources=("daily-2024-01-02",),
        status="active",
        notes=None,
    )
    section = PersistentMemorySection(name="Praca i Produktywność", facts=[fact_a, fact_b])

    updated_a = fact_a.merge(
        PersistentFact(
            id="fact-a",
            statement="Uses GTD with weekly reviews",
            category="productivity",
            confidence=0.85,
            first_seen=date(2024, 1, 1),
            last_seen=date(2024, 2, 1),
            sources=("weekly-2024-02",),
            status="active",
            notes="Extended routine",
        )
    )
    addition = PersistentFact(
        id="fact-c",
        statement="Prefers async status updates",
        category="communication",
        confidence=0.9,
        first_seen=date(2024, 2, 3),
        last_seen=date(2024, 2, 3),
        sources=("weekly-2024-02",),
        status="active",
        notes=None,
    )

    updated_section = section.diff(
        additions=[addition],
        updates=[updated_a],
        removals=["fact-b"],
    )

    assert [fact.id for fact in updated_section.facts] == ["fact-a", "fact-c"]
    assert updated_section.facts[0].statement == "Uses GTD with weekly reviews"
    assert updated_section.facts[1].statement == "Prefers async status updates"
