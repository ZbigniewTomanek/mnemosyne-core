from __future__ import annotations

from telegram_bot.service.persistent_memory.document import PersistentMemoryDelta, PersistentMemoryDocument
from telegram_bot.service.persistent_memory.models import PersistentFact


def test_parse_document_roundtrip(sample_document_markdown: str) -> None:
    document = PersistentMemoryDocument.parse(sample_document_markdown)

    assert document.frontmatter["consolidation_type"] == "persistent"
    assert document.frontmatter["last_updated"] == "2024-05-01"
    assert document.sections[0].name == "Zdrowie i Samopoczucie"
    assert document.sections[1].facts[0].statement == "Prefers async collaboration"

    rendered = document.render()
    assert rendered == sample_document_markdown


def test_apply_section_deltas(sample_document_markdown: str) -> None:
    document = PersistentMemoryDocument.parse(sample_document_markdown)
    section = document.sections[0]

    updated_fact = PersistentFact(
        id="health-1",
        statement="Maintains hydration habit",
        category="habit",
        confidence=0.95,
        first_seen=None,
        last_seen=None,
        sources=("note-2024-04-15", "note-2024-04-20"),
        status="active",
        notes=None,
    )
    new_fact = PersistentFact(
        id="health-2",
        statement="Meditates every morning",
        category="routine",
        confidence=0.8,
        first_seen=None,
        last_seen=None,
        sources=("note-2024-04-25",),
        status="active",
        notes="Added by LLM",
    )

    delta = PersistentMemoryDelta(
        additions=(new_fact,),
        updates=(updated_fact,),
        removals=("non-existent",),
    )

    updated_document = document.apply_changes({section.name: delta})

    health_section = next(s for s in updated_document.sections if s.name == section.name)
    assert len(health_section.facts) == 2
    assert any(fact.id == "health-2" for fact in health_section.facts)
    assert any(fact.statement == "Maintains hydration habit" for fact in health_section.facts)

    rendered = updated_document.render()
    assert "Meditates every morning" in rendered
    assert "Maintains hydration habit" in rendered
