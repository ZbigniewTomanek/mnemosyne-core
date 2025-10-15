from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from telegram_bot.config import CorrelationEngineConfig
from telegram_bot.service.correlation_engine.job import CorrelationJobRunner, EventSource
from telegram_bot.service.correlation_engine.models import CorrelationEvent, CorrelationRunSummary


class StubEventSource:
    def __init__(self, events: list[CorrelationEvent]):
        self.events = events
        self.calls: int = 0

    async def fetch_events(self, job_config):  # noqa: D401 - simple test stub signature
        self.calls += 1
        return list(self.events)


class RecordingEngine:
    def __init__(self):
        self.requests: list = []

    async def run(self, request):
        self.requests.append(request)
        now = datetime.now(UTC)
        return CorrelationRunSummary(
            run_id="test",
            started_at=now,
            completed_at=now,
            user_id=request.user_id,
            window_days=request.config.lookback_days,
            results=[],
            discarded_events=[],
        )


@pytest.mark.asyncio
async def test_job_runner_merges_and_sorts_events():
    now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    calendar_event = CorrelationEvent(
        id="shared",
        title="Calendar Block",
        start=now,
        end=now + timedelta(hours=1),
        source="calendar",
    )
    activity_event = CorrelationEvent(
        id="shared",
        title="Workout",
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1, minutes=30),
        source="garmin_activity",
    )
    secondary_calendar_event = CorrelationEvent(
        id="other",
        title="Meeting",
        start=now + timedelta(hours=1),
        end=now + timedelta(hours=2),
        source="calendar",
    )

    engine = RecordingEngine()
    sources: list[EventSource] = [
        StubEventSource([calendar_event, secondary_calendar_event]),
        StubEventSource([activity_event]),
    ]

    config = CorrelationEngineConfig()
    runner = CorrelationJobRunner(
        engine=engine,
        event_sources=sources,
        config=config,
        user_id=123,
    )

    summary = await runner.run()

    assert summary.window_days == config.lookback_days
    assert summary.telemetry["raw_event_count"] == 3
    assert summary.telemetry["deduplicated_event_count"] == 2
    request = engine.requests[0]
    assert len(request.events) == 2, "Shared event should be deduplicated"
    assert [event.id for event in request.events] == ["shared", "other"], "Events sorted by start time"
    assert request.events[0].title == "Workout", "Latest occurrence for shared id should win"
    assert summary.telemetry["per_source_counts"]["StubEventSource"] == 3


@pytest.mark.asyncio
async def test_job_runner_handles_source_failures_gracefully():
    class FailingSource:
        async def fetch_events(self, job_config):  # noqa: D401 - test stub signature
            raise RuntimeError("boom")

    now = datetime(2024, 1, 1, tzinfo=UTC)
    fallback_event = CorrelationEvent(
        id="ok",
        title="Fallback",
        start=now,
        end=now + timedelta(hours=1),
        source="calendar",
    )

    engine = RecordingEngine()
    runner = CorrelationJobRunner(
        engine=engine,
        event_sources=[FailingSource(), StubEventSource([fallback_event])],
        config=CorrelationEngineConfig(),
        user_id=123,
    )

    summary = await runner.run()
    assert summary.results == []
    request = engine.requests[0]
    assert request.events == [fallback_event]
    assert summary.telemetry["raw_event_count"] == 1
