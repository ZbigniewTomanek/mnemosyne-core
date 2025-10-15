from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from telegram_bot.service.db_service import ActivityImpactVarianceEntry, CorrelationEventRecord, CorrelationMetricRecord
from telegram_bot.service.life_context import (
    LifeContextConfig,
    LifeContextMetric,
    LifeContextRequest,
    LifeContextService,
)


class FakeObsidianService:
    def __init__(self) -> None:
        self.notes_calls: list[tuple[date, date, int | None]] = []
        self.persistent_calls = 0
        self.daily_notes_return: dict[str, str] = {"2024-01-10": "Note content"}
        self.persistent_return = "Persistent memory"

    async def get_daily_notes_between(
        self, start_date: date, end_date: date, max_notes: int | None = None
    ) -> dict[str, str]:
        self.notes_calls.append((start_date, end_date, max_notes))
        return self.daily_notes_return

    async def get_persistent_memory_content(self) -> str:
        self.persistent_calls += 1
        return self.persistent_return

    async def add_ai_log_entry(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError


class FakeGarminService:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []
        self.return_value = {"garmin": "metrics"}

    async def get_window(self, start_date: date, end_date: date) -> dict[str, Any]:
        self.calls.append((start_date, end_date))
        return self.return_value


class FakeCalendarService:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date, int | None]] = []
        self.return_value = {"events": []}

    async def get_events_between(self, start_date: date, end_date: date, limit: int | None = None) -> dict[str, Any]:
        self.calls.append((start_date, end_date, limit))
        return self.return_value


class FakeDBService:
    def __init__(self) -> None:
        self.correlation_calls: list[tuple[date, date, int]] = []
        self.variance_calls: list[tuple[date, date, int, float]] = []
        now = datetime.now(UTC)
        metric_record = CorrelationMetricRecord(
            metric="stress",
            effect_size=1.5,
            effect_direction="increase",
            confidence=0.95,
            p_value=0.01,
            sample_count=6,
            baseline_mean=10.0,
            post_event_mean=12.5,
            notes=None,
        )
        start_time = now - timedelta(days=2)
        end_time = start_time + timedelta(hours=1)
        self.correlation_return = [
            CorrelationEventRecord(
                run_id="run-1",
                event_id="event-1",
                source="calendar",
                title="Deep Work Block",
                start=start_time,
                end=end_time,
                categories=("focus",),
                metadata={},
                supporting_evidence={},
                metrics=(metric_record,),
                run_started_at=start_time - timedelta(hours=1),
                run_completed_at=end_time,
                run_window_days=3,
                run_config={},
            )
        ]
        self.variance_return = [
            ActivityImpactVarianceEntry(
                variance_id="var-1",
                run_id="run-variance",
                event_id="event-123",
                title_key="sleep_quality",
                raw_title="Sleep Quality",
                metric="stress",
                window_start=now - timedelta(days=7),
                window_end=now - timedelta(days=6),
                baseline_mean=8.5,
                baseline_stddev=1.2,
                baseline_sample_count=10,
                current_effect=5.5,
                delta=-3.0,
                normalised_score=-2.4,
                trend="decrease",
                metadata_json=None,
                created_at=now,
                config_hash="hash",
            )
        ]

    def fetch_correlation_events(
        self,
        *,
        lookback_days: int,
        limit: int | None = None,
        sources: set[str] | None = None,
    ) -> list[CorrelationEventRecord]:
        self.correlation_calls.append((lookback_days, limit, sources))
        return self.correlation_return

    def fetch_activity_variances(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        limit: int | None,
        min_score: float,
    ) -> list[ActivityImpactVarianceEntry]:
        self.variance_calls.append((start_date, end_date, limit, min_score))
        return self.variance_return


@pytest.mark.asyncio
async def test_service_fetches_requested_metrics_only() -> None:
    obsidian = FakeObsidianService()
    garmin = FakeGarminService()
    calendar = FakeCalendarService()
    db = FakeDBService()
    config = LifeContextConfig(
        default_lookback_days=3,
        max_token_budget=4000,
    )

    service = LifeContextService(
        config=config,
        tz=ZoneInfo("UTC"),
        obsidian_service=obsidian,
        garmin_service=garmin,
        calendar_service=calendar,
        db_service=db,
    )

    request = LifeContextRequest(
        end_date=date(2024, 1, 10),
        metrics=[LifeContextMetric.NOTES, LifeContextMetric.GARMIN],
    )

    await service.build_context(request)

    assert len(obsidian.notes_calls) == 1
    assert obsidian.persistent_calls == 0
    assert len(garmin.calls) == 1
    assert calendar.calls == []
    assert db.correlation_calls == []
    assert db.variance_calls == []


@pytest.mark.asyncio
async def test_request_all_metrics_triggers_all_services() -> None:
    obsidian = FakeObsidianService()
    garmin = FakeGarminService()
    calendar = FakeCalendarService()
    db = FakeDBService()
    config = LifeContextConfig(
        default_lookback_days=3,
        max_token_budget=4000,
        correlation_limit=5,
        variance_limit=3,
        variance_min_score=0.5,
    )

    service = LifeContextService(
        config=config,
        tz=ZoneInfo("UTC"),
        obsidian_service=obsidian,
        garmin_service=garmin,
        calendar_service=calendar,
        db_service=db,
    )

    request = LifeContextRequest(end_date=date(2024, 1, 10), metrics="all")

    await service.build_context(request)

    assert len(obsidian.notes_calls) == 1
    assert obsidian.persistent_calls == 1
    assert len(garmin.calls) == 1
    assert len(calendar.calls) == 1
    assert len(db.correlation_calls) == 1
    assert len(db.variance_calls) == 1


@pytest.mark.asyncio
async def test_response_sections_include_structured_markdown() -> None:
    obsidian = FakeObsidianService()
    garmin = FakeGarminService()
    calendar = FakeCalendarService()
    db = FakeDBService()

    service = LifeContextService(
        config=LifeContextConfig(default_lookback_days=1, max_token_budget=4000),
        tz=ZoneInfo("UTC"),
        obsidian_service=obsidian,
        garmin_service=garmin,
        calendar_service=calendar,
        db_service=db,
    )

    response = await service.build_context(LifeContextRequest(end_date=date(2024, 1, 10), metrics="all"))

    assert response.rendered_markdown is not None
    assert "### Daily Notes" in response.rendered_markdown

    notes_section = response.sections[LifeContextMetric.NOTES.value]
    assert notes_section["data"]["items"][0]["date"] == "2024-01-10"
    assert "Note content" in notes_section["markdown"]

    correlations_section = response.sections[LifeContextMetric.CORRELATIONS.value]
    assert correlations_section["markdown"]
    correlation_data = correlations_section["data"][0]
    assert correlation_data["title"] == "Deep Work Block"

    variance_section = response.sections[LifeContextMetric.VARIANCE.value]
    assert variance_section["markdown"]
    variance_data = variance_section["data"][0]
    assert variance_data["raw_title"] == "Sleep Quality"


@pytest.mark.asyncio
async def test_default_start_date_uses_configured_lookback() -> None:
    obsidian = FakeObsidianService()
    garmin = FakeGarminService()
    calendar = FakeCalendarService()
    db = FakeDBService()

    config = LifeContextConfig(default_lookback_days=2, max_token_budget=4000)

    service = LifeContextService(
        config=config,
        tz=ZoneInfo("UTC"),
        obsidian_service=obsidian,
        garmin_service=garmin,
        calendar_service=calendar,
        db_service=db,
    )

    request = LifeContextRequest(end_date=date(2024, 1, 10), metrics=[LifeContextMetric.NOTES])

    await service.build_context(request)

    assert obsidian.notes_calls
    start_date, end_date, _ = obsidian.notes_calls[0]
    assert start_date == date(2024, 1, 9)
    assert end_date == date(2024, 1, 10)


@pytest.mark.asyncio
async def test_token_budget_exceeded_returns_error() -> None:
    obsidian = FakeObsidianService()
    obsidian.daily_notes_return = {"2024-01-10": "#" * 500}
    garmin = FakeGarminService()
    calendar = FakeCalendarService()
    db = FakeDBService()

    config = LifeContextConfig(default_lookback_days=2, max_token_budget=10)

    service = LifeContextService(
        config=config,
        tz=ZoneInfo("UTC"),
        obsidian_service=obsidian,
        garmin_service=garmin,
        calendar_service=calendar,
        db_service=db,
    )

    request = LifeContextRequest(end_date=date(2024, 1, 10), metrics=[LifeContextMetric.NOTES])

    response = await service.build_context(request)

    assert response.error is not None
    assert "token" in response.error.lower()
    assert response.rendered_markdown is None
