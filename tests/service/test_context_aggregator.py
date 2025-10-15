from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from telegram_bot.service.context_trigger.context_aggregator import ContextAggregator
from telegram_bot.service.context_trigger.models import ContextTriggerConfig
from telegram_bot.service.correlation_engine.models import CorrelationFetchConfig
from telegram_bot.service.life_context.models import (
    LifeContextBundle,
    LifeContextFormattedResponse,
    LifeContextMetric,
    LifeContextRequest,
)
from telegram_bot.service.llm_service import LLMConfig


class FakeLifeContextService:
    def __init__(self, response: LifeContextFormattedResponse) -> None:
        self.response = response
        self.requests: list[LifeContextRequest] = []

    async def build_context(self, request: LifeContextRequest) -> LifeContextFormattedResponse:
        self.requests.append(request)
        return self.response


def _dummy_llm_config() -> LLMConfig:
    return LLMConfig(llm_class_path="tests.dummy.Dummy", llm_kwargs={})


@pytest.mark.asyncio
async def test_gather_context_uses_life_context_service_and_limits_sections() -> None:
    tz = ZoneInfo("UTC")
    frozen_now = datetime(2024, 1, 10, tzinfo=tz)

    notes_items = [
        {"date": "2024-01-10", "content": "Note A"},
        {"date": "2024-01-09", "content": "Note B"},
        {"date": "2024-01-08", "content": "Note C"},
    ]

    response = LifeContextFormattedResponse(
        bundle=LifeContextBundle(
            start_date=frozen_now.date() - timedelta(days=4),
            end_date=frozen_now.date() + timedelta(days=2),
        ),
        sections={
            "notes": {
                "data": {"items": notes_items},
                "markdown": "\n\n".join(f"**{item['date']}**\n{item['content']}" for item in notes_items),
            },
            "garmin": {
                "data": {"summary": "garmin"},
                "markdown": "Garmin summary",
            },
            "calendar": {
                "data": {"events": ["Meeting"]},
                "markdown": "Today\n- 12:00 Meeting",
            },
            "correlations": {
                "data": [{"title": "Deep Work", "effect": 1.2}],
                "markdown": "Deep Work correlation",
            },
            "variance": {
                "data": [{"raw_title": "Sleep Quality"}],
                "markdown": "Sleep Quality variance",
            },
        },
        rendered_markdown=None,
        error=None,
    )

    fake_service = FakeLifeContextService(response)
    aggregator = ContextAggregator(
        life_context_service=fake_service,
        tz=tz,
        now_provider=lambda: frozen_now,
    )

    config = ContextTriggerConfig(
        name="Test Trigger",
        llm_config=_dummy_llm_config(),
        prompt_template="Template",
        garmin_lookback_days=3,
        obsidian_lookback_days=2,
        calendar_lookback_days=1,
        calendar_lookahead_days=2,
        correlation_fetch=CorrelationFetchConfig(lookback_days=4, max_events=3),
    )

    context_markdown = await aggregator.gather_context(config)

    assert "GARMIN HEALTH DATA" in context_markdown
    assert "RECENT DAILY NOTES" in context_markdown
    assert "Note A" in context_markdown
    assert "Note B" in context_markdown
    assert "Note C" not in context_markdown, "notes should be limited to the configured lookback"
    assert "CALENDAR EVENTS" in context_markdown
    assert "CORRELATION HIGHLIGHTS" in context_markdown
    assert "VARIANCE HIGHLIGHTS" in context_markdown

    assert fake_service.requests, "LifeContextService should be invoked"
    request = fake_service.requests[0]
    expected_metrics = {
        LifeContextMetric.NOTES,
        LifeContextMetric.GARMIN,
        LifeContextMetric.CALENDAR,
        LifeContextMetric.CORRELATIONS,
        LifeContextMetric.VARIANCE,
    }
    assert request.metrics == expected_metrics
    assert request.start_date == frozen_now.date() - timedelta(days=4)
    assert request.end_date == frozen_now.date() + timedelta(days=2)


@pytest.mark.asyncio
async def test_gather_context_returns_placeholder_when_no_sections() -> None:
    tz = ZoneInfo("UTC")
    frozen_now = datetime(2024, 1, 10, tzinfo=tz)

    response = LifeContextFormattedResponse(
        bundle=LifeContextBundle(
            start_date=frozen_now.date(),
            end_date=frozen_now.date(),
        ),
        sections={},
        rendered_markdown=None,
        error=None,
    )

    fake_service = FakeLifeContextService(response)
    aggregator = ContextAggregator(
        life_context_service=fake_service,
        tz=tz,
        now_provider=lambda: frozen_now,
    )

    config = ContextTriggerConfig(
        name="Empty Trigger",
        llm_config=_dummy_llm_config(),
        prompt_template="Template",
    )

    context_markdown = await aggregator.gather_context(config)

    assert context_markdown.strip() == "NO CONTEXT DATA AVAILABLE"
