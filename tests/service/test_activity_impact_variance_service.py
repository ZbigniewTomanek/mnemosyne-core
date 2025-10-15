from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from telegram_bot.service.correlation_engine.models import (
    ActivityImpactVarianceConfig,
    BioSignalType,
    CorrelationEvent,
    CorrelationJobConfig,
    CorrelationRunSummary,
    EventCorrelationResult,
    MetricEffect,
    MetricThreshold,
)
from telegram_bot.service.correlation_engine.variance import ActivityImpactVarianceService
from telegram_bot.service.db_service import ActivityImpactVarianceEntry, MetricObservationRecord


class StubDBService:
    def __init__(self, observations: list[MetricObservationRecord]):
        self._observations = observations
        self.variance_entries: list[ActivityImpactVarianceEntry] = []

    def fetch_metric_observations(self, *, lookback_days: int) -> list[MetricObservationRecord]:
        return [
            obs for obs in self._observations if obs.observed_at >= datetime.now(UTC) - timedelta(days=lookback_days)
        ]

    def add_activity_variance(self, entry: ActivityImpactVarianceEntry) -> None:
        self.variance_entries.append(entry)

    def activity_variance_exists(self, *, event_id: str, metric: str, config_hash: str) -> bool:
        return any(
            entry.event_id == event_id and entry.metric == metric and entry.config_hash == config_hash
            for entry in self.variance_entries
        )

    def get_activity_variance(
        self, *, event_id: str, metric: str, config_hash: str
    ) -> ActivityImpactVarianceEntry | None:
        for entry in reversed(self.variance_entries):
            if entry.event_id == event_id and entry.metric == metric and entry.config_hash == config_hash:
                return entry
        return None


def _make_metric_effect(metric: BioSignalType, effect_size: float) -> MetricEffect:
    return MetricEffect(
        metric=metric,
        effect_size=effect_size,
        effect_direction="increase" if effect_size > 0 else "decrease",
        confidence=0.9,
        p_value=0.05,
        sample_count=6,
    )


def _make_observation(
    *,
    event_id: str,
    title: str,
    metric: BioSignalType,
    effect_size: float,
    observed_at: datetime,
) -> MetricObservationRecord:
    return MetricObservationRecord(
        run_id="run-previous",
        event_id=event_id,
        title=title,
        metric=metric.value,
        effect_size=effect_size,
        is_triggered=True,
        observed_at=observed_at,
        source="calendar",
        categories=(),
        metadata={},
    )


@pytest.mark.asyncio
async def test_activity_variance_service_computes_z_score_and_persists_entries(monkeypatch):
    now = datetime.now(UTC)
    historical_obs = [
        _make_observation(
            event_id=f"past-{i}",
            title="Focus Sprint",
            metric=BioSignalType.STRESS,
            effect_size=val,
            observed_at=now - timedelta(days=5 - i),
        )
        for i, val in enumerate([2.0, 4.0, 6.0])
    ]

    db = StubDBService(observations=historical_obs)
    service = ActivityImpactVarianceService(db_service=db, clock=lambda: now)

    event = CorrelationEvent(
        id="event-current",
        title="Focus Sprint",
        start=now - timedelta(hours=1),
        end=now,
        source="calendar",
    )
    effect = _make_metric_effect(BioSignalType.STRESS, 10.0)
    result = EventCorrelationResult(event=event, evaluated_metrics=[effect], triggered_metrics=[effect])
    summary = CorrelationRunSummary(
        run_id="run-current",
        started_at=now - timedelta(minutes=30),
        completed_at=now,
        user_id=1,
        window_days=7,
        results=[result],
        discarded_events=[],
    )

    job_config = CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        metrics={BioSignalType.STRESS: MetricThreshold()},
        variance_analysis=ActivityImpactVarianceConfig(
            enabled=True,
            lookback_days=30,
            min_samples=3,
            min_score_for_alert=1.0,
            max_alerts=3,
        ),
    )

    results = await service.compute_for_run(summary, job_config)

    assert len(results) == 1
    variance = results[0]
    assert variance.metric == BioSignalType.STRESS
    assert variance.baseline_mean == pytest.approx(4.0)
    assert variance.baseline_stddev > 0
    assert variance.normalised_score > 1.0
    assert db.variance_entries, "Variance entry should be persisted"
    stored = db.variance_entries[0]
    assert stored.metric == "stress"
    assert stored.delta == pytest.approx(variance.delta)
    assert variance.config_hash == stored.config_hash


@pytest.mark.asyncio
async def test_activity_variance_service_skips_when_insufficient_samples():
    now = datetime.now(UTC)
    historical_obs = [
        _make_observation(
            event_id="past-1",
            title="Team Sync",
            metric=BioSignalType.BODY_BATTERY,
            effect_size=1.0,
            observed_at=now - timedelta(days=1),
        )
    ]

    db = StubDBService(observations=historical_obs)
    service = ActivityImpactVarianceService(db_service=db, clock=lambda: now)

    event = CorrelationEvent(
        id="event-current",
        title="Team Sync",
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1),
        source="calendar",
    )
    effect = _make_metric_effect(BioSignalType.BODY_BATTERY, 2.0)
    result = EventCorrelationResult(event=event, evaluated_metrics=[effect], triggered_metrics=[])
    summary = CorrelationRunSummary(
        run_id="run-current",
        started_at=now - timedelta(minutes=30),
        completed_at=now,
        user_id=1,
        window_days=7,
        results=[result],
        discarded_events=[],
    )

    job_config = CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        metrics={},
        variance_analysis=ActivityImpactVarianceConfig(
            enabled=True,
            lookback_days=30,
            min_samples=3,
            min_score_for_alert=1.0,
            max_alerts=3,
        ),
    )

    results = await service.compute_for_run(summary, job_config)

    assert results == []
    assert not db.variance_entries


@pytest.mark.asyncio
async def test_activity_variance_service_uses_existing_entries_when_already_persisted():
    now = datetime.now(UTC)
    observations = [
        _make_observation(
            event_id=f"past-{i}",
            title="Focus Sprint",
            metric=BioSignalType.STRESS,
            effect_size=3.0 + i,
            observed_at=now - timedelta(days=3 - i),
        )
        for i in range(3)
    ]
    db = StubDBService(observations=observations)
    service = ActivityImpactVarianceService(db_service=db, clock=lambda: now)

    event = CorrelationEvent(
        id="event-current",
        title="Focus Sprint",
        start=now - timedelta(hours=1),
        end=now,
        source="calendar",
    )
    effect = _make_metric_effect(BioSignalType.STRESS, 6.0)
    result = EventCorrelationResult(event=event, evaluated_metrics=[effect], triggered_metrics=[effect])
    summary = CorrelationRunSummary(
        run_id="run-1",
        started_at=now - timedelta(minutes=10),
        completed_at=now,
        user_id=1,
        window_days=7,
        results=[result],
        discarded_events=[],
    )
    job_config = CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        metrics={},
        variance_analysis=ActivityImpactVarianceConfig(),
    )

    # First run persists entry
    first_results = await service.compute_for_run(summary, job_config)
    assert len(first_results) == 1
    assert len(db.variance_entries) == 1

    # Second run should reuse existing entry rather than adding a duplicate
    second_results = await service.compute_for_run(summary, job_config)
    assert len(second_results) == 1
    assert len(db.variance_entries) == 1
    assert second_results[0].delta == pytest.approx(first_results[0].delta)
