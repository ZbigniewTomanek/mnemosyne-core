from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telegram_bot.scheduled_tasks.memory_consolidation_task import (
    MemoryConsolidationTaskConfig,
    WeeklySummaryReflectiveOutput,
    _run_consolidation_logic,
)
from telegram_bot.service.persistent_memory.llm_models import PersistentMemoryLLMResponse


class StubSummaryLLM:
    async def aprompt_llm_with_structured_output(self, prompt: str, output_type: type) -> WeeklySummaryReflectiveOutput:
        return WeeklySummaryReflectiveOutput(
            wazne_wydarzenia=["Event A"],
            refleksja_samopoczucie="Good",
            refleksja_sny=None,
            refleksja_zdrowie="Stable",
            refleksja_praca="Productive",
            refleksja_co_sie_zmienia="More consistent routines",
            refleksja_co_bylo_przyjemne=["Walk in the park"],
            refleksja_co_bylo_nieprzyjemne=["Long meeting"],
            refleksja_co_poszlo_zle="Missed workout",
        )


class StubFactLLM:
    async def aprompt_llm_with_structured_output(self, prompt: str, output_type: type) -> PersistentMemoryLLMResponse:
        payload = {
            "sections": [
                {
                    "name": "Zdrowie i Samopoczucie",
                    "add": [
                        {
                            "statement": "Practices breathwork every evening",
                            "category": "health",
                            "confidence": 0.8,
                            "sources": ["note-2024-05-20"],
                        }
                    ],
                    "update": [
                        {
                            "id": "health-1",
                            "statement": "Drinks two liters of water daily",
                            "category": "health",
                            "confidence": 0.95,
                            "first_seen": "2024-04-01",
                            "last_seen": "2024-05-20",
                            "sources": ["note-2024-04-15", "note-2024-05-20"],
                        }
                    ],
                    "remove": [],
                },
                {
                    "name": "Praca",
                    "add": [],
                    "update": [],
                    "remove": ["work-1"],
                },
            ]
        }
        return PersistentMemoryLLMResponse.model_validate(payload)


class StubObsidianService:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def get_daily_note_path(self, note_date) -> Path:
        path = self.base_path / "daily" / f"{note_date.isoformat()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def safe_read_file(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    async def safe_write_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def get_weekly_memory_path(self, year: int, week_num: int, directory: str) -> Path:
        path = self.base_path / directory / f"{year}-W{week_num:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_persistent_memory_path(self, relative: str | None = None) -> Path:
        relative_path = relative or "persistent_memory.md"
        path = self.base_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def generate_obsidian_link(self, name: str) -> str:
        return f"[[{name}]]"


@pytest.mark.asyncio
async def test_run_consolidation_logic_updates_persistent_memory(tmp_path: Path) -> None:
    obsidian_root = tmp_path / "vault"
    obsidian_root.mkdir(parents=True, exist_ok=True)
    obsidian_service = StubObsidianService(obsidian_root)

    tz = timezone(timedelta(hours=2))
    today = datetime.now(tz=tz).date()
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7)

    for offset in range(7):
        note_date = last_monday + timedelta(days=offset)
        daily_path = obsidian_service.get_daily_note_path(note_date)
        daily_path.write_text(f"Daily note {note_date}", encoding="utf-8")

    persistent_path = obsidian_service.get_persistent_memory_path("persistent/persistent_memory.md")
    persistent_path.write_text(
        "---\nconsolidation_type: persistent\nlast_updated: 2024-05-01\ntags:\n- ai_memory\n- persistent_facts\n---\n\n"
        "## Zdrowie i Samopoczucie\n\n"
        "| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| health-1 | Drinks two liters of water daily | habit | 0.9 | 2024-04-01 | 2024-04-15 | note-2024-04-15 | active | |\n\n"  # noqa: E501
        "## Praca i Produktywność\n\n"
        "| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| work-1 | Prefers async collaboration | productivity |  | 2024-03-01 | 2024-03-10 | weekly-2024-10 | active | keep meetings short |\n",  # noqa: E501
        encoding="utf-8",
    )

    config = MemoryConsolidationTaskConfig(
        weekly_memory_dir="weekly",
        persistent_memory_file="persistent/persistent_memory.md",
        weekly_summary_prompt="{combined_content}",
        fact_extraction_prompt="{combined_content}",
    )

    summary_llm = StubSummaryLLM()
    fact_llm = StubFactLLM()

    result = await _run_consolidation_logic(config, obsidian_service, summary_llm, fact_llm)

    assert result["status"] == "success"
    assert result["facts_extracted"] == 1
    assert result["facts_updated"] == 1
    assert result["facts_removed"] == 1
    assert "Praca i Produktywność" in result["persistent_memory_delta"]

    updated_content = persistent_path.read_text(encoding="utf-8")
    assert "Practices breathwork every evening" in updated_content
    assert "Prefers async collaboration" not in updated_content
