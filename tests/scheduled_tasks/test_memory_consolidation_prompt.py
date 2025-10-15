from __future__ import annotations

import json
from datetime import date

from telegram_bot.scheduled_tasks.memory_consolidation_task import _format_persistent_memory_snapshot
from telegram_bot.service.persistent_memory.document import PersistentMemoryDocument
from telegram_bot.service.persistent_memory.models import PersistentFact, PersistentMemorySection


def test_format_persistent_memory_snapshot_serializes_sections() -> None:
    section = PersistentMemorySection(
        name="Zdrowie i Samopoczucie",
        facts=[
            PersistentFact(
                id="health-adhd",
                statement="ADHD zostało zdiagnozowane",
                category="health",
                confidence=0.9,
                first_seen=date(2024, 5, 1),
                last_seen=date(2024, 5, 7),
                sources=("2024-05-01", "2024-05-07"),
                status="active",
                notes=None,
            )
        ],
    )
    document = PersistentMemoryDocument(frontmatter={}, sections=(section,))

    snapshot = _format_persistent_memory_snapshot(document)
    payload = json.loads(snapshot)

    facts = payload["sections"]["Zdrowie i Samopoczucie"]
    assert facts[0]["id"] == "health-adhd"
    assert facts[0]["first_seen"] == "2024-05-01"
    assert facts[0]["last_seen"] == "2024-05-07"
    assert facts[0]["sources"] == ["2024-05-01", "2024-05-07"]
    assert facts[0]["notes"] is None


def test_format_persistent_memory_snapshot_handles_empty_document() -> None:
    document = PersistentMemoryDocument(frontmatter={}, sections=())

    snapshot = _format_persistent_memory_snapshot(document)
    payload = json.loads(snapshot)

    assert payload == {"sections": {}}
