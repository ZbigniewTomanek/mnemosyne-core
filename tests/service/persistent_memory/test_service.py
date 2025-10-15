from __future__ import annotations

from datetime import datetime

import pytest

from telegram_bot.service.persistent_memory.document import PersistentMemoryDelta
from telegram_bot.service.persistent_memory.models import PersistentFact
from telegram_bot.service.persistent_memory.service import (
    FileSystemPersistentMemoryRepository,
    PersistentMemoryUpdater,
    SectionRoutingConfig,
)


@pytest.mark.asyncio
async def test_updater_applies_deltas_and_saves(sample_document_markdown: str) -> None:
    saved: dict[str, str] = {}

    async def loader() -> str:
        return sample_document_markdown

    async def saver(content: str) -> None:
        saved["content"] = content

    repository = FileSystemPersistentMemoryRepository(loader=loader, saver=saver)
    updater = PersistentMemoryUpdater(
        repository=repository,
        routing=SectionRoutingConfig(category_to_section={}, default_section="Zdrowie i Samopoczucie"),
        now_factory=lambda: datetime(2024, 5, 5, 12, 0, 0),
    )

    health_update = PersistentFact(
        id="health-1",
        statement="Maintains hydration habit",
        category="habit",
        confidence=0.95,
        first_seen=None,
        last_seen=None,
        sources=("note-2024-04-20",),
        status="active",
        notes=None,
    )
    health_addition = PersistentFact(
        id="",  # expect updater to generate deterministic id
        statement="Meditates every morning",
        category="routine",
        confidence=0.8,
        first_seen=None,
        last_seen=None,
        sources=("note-2024-04-25",),
        status="active",
        notes="Added by LLM",
    )

    work_delta = PersistentMemoryDelta(
        additions=(),
        updates=(),
        removals=("work-1",),
    )

    updated_document = await updater.update(
        {
            "Zdrowie i Samopoczucie": PersistentMemoryDelta(
                additions=(health_addition,),
                updates=(health_update,),
                removals=(),
            ),
            "Praca i Produktywność": work_delta,
        }
    )

    assert "content" in saved
    saved_content = saved["content"]

    assert "Meditates every morning" in saved_content
    assert "Prefers async collaboration" not in saved_content
    assert "Maintains hydration habit" in saved_content
    assert updated_document.frontmatter["last_updated"] == "2024-05-05"
    assert updater.last_summary["Zdrowie i Samopoczucie"]["add"] == 1
    assert updater.last_summary["Zdrowie i Samopoczucie"]["update"] == 1
    assert updater.last_summary["Praca i Produktywność"]["remove"] == 1


@pytest.mark.asyncio
async def test_updater_routes_unknown_section_via_category(sample_document_markdown: str) -> None:
    async def loader() -> str:
        return sample_document_markdown

    saved: dict[str, str] = {}

    async def saver(content: str) -> None:
        saved["content"] = content

    repository = FileSystemPersistentMemoryRepository(loader=loader, saver=saver)
    updater = PersistentMemoryUpdater(
        repository=repository,
        routing=SectionRoutingConfig(
            category_to_section={"productivity": "Praca i Produktywność"},
            default_section="Zdrowie i Samopoczucie",
        ),
        now_factory=lambda: datetime(2024, 6, 1, 9, 0, 0),
    )

    routed_fact = PersistentFact(
        id="",
        statement="Uses GTD inbox for daily capture",
        category="productivity",
        confidence=0.9,
        first_seen=None,
        last_seen=None,
        sources=("note-2024-05-20",),
        status="active",
        notes=None,
    )

    await updater.update({"Unknown": PersistentMemoryDelta(additions=(routed_fact,), updates=(), removals=())})

    assert "content" in saved
    content = saved["content"]
    assert "## Praca i Produktywność" in content
    assert "Uses GTD inbox for daily capture" in content
    assert updater.last_summary["Praca i Produktywność"]["add"] == 1
