from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from telegram_bot.service.correlation_engine.engine import CorrelationEngine
from telegram_bot.service.correlation_engine.models import (
    BioSignalType,
    CorrelationEvent,
    CorrelationJobConfig,
    CorrelationRunRequest,
    MetricThreshold,
    SleepCorrelationConfig,
    TimeSeriesPoint,
    WindowConfig,
)
from telegram_bot.service.correlation_engine.sleep import SleepMatch, SleepSession
from telegram_bot.service.correlation_engine.stats import WelchTTest
from telegram_bot.service.db_service import CorrelationEventEntry, CorrelationMetricEntry, CorrelationRunEntry


class StubMetricSource:
    def __init__(self, dataset: dict[tuple[BioSignalType, datetime, datetime], list[TimeSeriesPoint]]):
        self._dataset = dataset

    async def fetch_series(self, metric, start, end, sample_frequency):
        return self._dataset[(metric, start, end)]


class RecordingDBService:
    def __init__(self):
        self.runs: list[CorrelationRunEntry] = []
        self.events: list[CorrelationEventEntry] = []
        self.metrics: list[CorrelationMetricEntry] = []

    def add_correlation_run(self, entry: CorrelationRunEntry) -> None:
        self.runs.append(entry)

    def add_correlation_event(self, entry: CorrelationEventEntry) -> None:
        self.events.append(entry)

    def add_correlation_metric(self, entry: CorrelationMetricEntry) -> None:
        self.metrics.append(entry)

    def correlation_metric_exists(self, *, event_id: str, metric: str) -> bool:
        return any(m.event_id == event_id and m.metric == metric for m in self.metrics)


class StubSleepService:
    def __init__(self, match: SleepMatch | None):
        self._match = match
        self.prepare_calls = 0

    async def prepare(self, request):  # noqa: D401 - simple stub
        self.prepare_calls += 1

    def match_event(self, event, config):  # noqa: D401 - simple stub
        return self._match


def _make_points(start: datetime, values: list[float], step: timedelta) -> list[TimeSeriesPoint]:
    return [TimeSeriesPoint(ts=start + i * step, value=v) for i, v in enumerate(values)]


@pytest.mark.asyncio
async def test_correlation_engine_detects_significant_increase():
    event = CorrelationEvent(
        id="event-1",
        title="Team Sync",
        start=datetime(2024, 1, 1, 9, 0, 0),
        end=datetime(2024, 1, 1, 10, 0, 0),
        source="calendar",
    )

    window_config = WindowConfig(baseline=timedelta(hours=1), post_event=timedelta(hours=1), sampling_freq="5min")
    config = CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        metrics={
            BioSignalType.STRESS: MetricThreshold(min_delta=5.0, min_samples=5, min_confidence=0.8),
        },
        windows=window_config,
    )

    request = CorrelationRunRequest(user_id=123, config=config, events=[event])

    baseline_start = event.start - timedelta(hours=1)
    baseline_end = event.start
    effect_start = event.start
    effect_end = event.end + timedelta(hours=1)
    baseline_values = [24, 25, 26, 24, 25, 26, 25, 24, 25, 24, 26, 25]
    effect_values = [42, 41, 43, 44, 42, 45, 43, 41, 44, 45, 42, 43]
    step = timedelta(minutes=5)

    dataset = {
        (BioSignalType.STRESS, baseline_start, baseline_end): _make_points(baseline_start, baseline_values, step),
        (BioSignalType.STRESS, effect_start, effect_end): _make_points(effect_start, effect_values, step),
    }
    metric_source = StubMetricSource(dataset)
    db_service = RecordingDBService()
    engine = CorrelationEngine(metric_source=metric_source, db_service=db_service, stats_calculator=WelchTTest())

    summary = await engine.run(request)

    assert summary.results, "Should return correlation results"
    result = summary.results[0]
    assert result.triggered_metrics, "Metric threshold should trigger"
    effect = result.triggered_metrics[0]
    assert effect.metric == BioSignalType.STRESS
    assert effect.effect_direction == "increase"
    assert effect.confidence >= 0.8
    assert effect.sample_count == len(effect_values)

    assert db_service.runs, "Run should be persisted"
    assert db_service.events, "Event should be persisted"
    assert db_service.metrics, "Metric effects should be persisted"


@pytest.mark.asyncio
async def test_correlation_engine_includes_sleep_analysis_effects():
    event = CorrelationEvent(
        id="event-sleep",
        title="Evening Workout",
        start=datetime(2024, 1, 1, 20, 0, 0),
        end=datetime(2024, 1, 1, 21, 0, 0),
        source="garmin_activity",
    )

    sleep_config = SleepCorrelationConfig(
        enabled=True,
        baseline_nights=3,
        lookahead_hours=24,
        main_sleep_only=True,
        metrics={
            BioSignalType.SLEEP: MetricThreshold(min_delta=5.0, min_samples=2, min_confidence=0.6),
        },
    )

    job_config = CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        metrics={},
        windows=WindowConfig(),
        sleep_analysis=sleep_config,
    )

    request = CorrelationRunRequest(user_id=123, config=job_config, events=[event])

    matched_session = SleepSession(
        start=datetime(2024, 1, 2, 23, 0, 0),
        end=datetime(2024, 1, 3, 7, 0, 0),
        is_main_sleep=True,
        metrics={"sleepScore": 85.0},
    )
    baseline_sessions = [
        SleepSession(
            start=datetime(2023, 12, 30, 23, 0, 0) + timedelta(days=i),
            end=datetime(2023, 12, 31, 7, 0, 0) + timedelta(days=i),
            is_main_sleep=True,
            metrics={"sleepScore": 70.0 + i},
        )
        for i in range(3)
    ]

    sleep_match = SleepMatch(event=event, matched_session=matched_session, baseline_sessions=baseline_sessions)
    sleep_service = StubSleepService(match=sleep_match)

    metric_source = StubMetricSource({})
    db_service = RecordingDBService()
    engine = CorrelationEngine(
        metric_source=metric_source,
        db_service=db_service,
        stats_calculator=WelchTTest(),
        sleep_service=sleep_service,
    )

    summary = await engine.run(request)

    assert sleep_service.prepare_calls == 1
    assert summary.results
    result = summary.results[0]
    assert any(effect.notes and effect.notes.startswith("sleep_analysis") for effect in result.evaluated_metrics)
    triggered_sleep = [effect for effect in result.triggered_metrics if effect.metric == BioSignalType.SLEEP]
    assert triggered_sleep, "Sleep metric should trigger with high delta"
    assert "sleep_analysis" in result.supporting_evidence


@pytest.mark.asyncio
async def test_correlation_engine_skips_duplicate_metrics():
    event = CorrelationEvent(
        id="event-duplicate",
        title="Weekly Review",
        start=datetime(2024, 1, 1, 9, 0, 0),
        end=datetime(2024, 1, 1, 10, 0, 0),
        source="calendar",
    )

    window_config = WindowConfig(baseline=timedelta(hours=1), post_event=timedelta(hours=1), sampling_freq="5min")
    config = CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        metrics={
            BioSignalType.STRESS: MetricThreshold(min_delta=5.0, min_samples=5, min_confidence=0.8),
        },
        windows=window_config,
    )

    request = CorrelationRunRequest(user_id=999, config=config, events=[event])

    baseline_start = event.start - timedelta(hours=1)
    baseline_end = event.start
    effect_start = event.start
    effect_end = event.end + timedelta(hours=1)
    baseline_values = [24, 25, 26, 24, 25, 26, 25, 24, 25, 24, 26, 25]
    effect_values = [42, 41, 43, 44, 42, 45, 43, 41, 44, 45, 42, 43]
    step = timedelta(minutes=5)

    dataset = {
        (BioSignalType.STRESS, baseline_start, baseline_end): _make_points(baseline_start, baseline_values, step),
        (BioSignalType.STRESS, effect_start, effect_end): _make_points(effect_start, effect_values, step),
    }
    metric_source = StubMetricSource(dataset)
    db_service = RecordingDBService()
    engine = CorrelationEngine(metric_source=metric_source, db_service=db_service, stats_calculator=WelchTTest())

    # First run should persist the metric
    await engine.run(request)
    assert len(db_service.metrics) == 1

    # Second run should skip adding a duplicate metric for the same event
    await engine.run(request)
    assert len(db_service.metrics) == 1
