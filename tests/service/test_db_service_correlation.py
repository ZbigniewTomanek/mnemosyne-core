import json
from datetime import UTC, datetime, timedelta

import pytest

from telegram_bot.service.db_service import (
    ActivityImpactVarianceEntry,
    CorrelationEventEntry,
    CorrelationMetricEntry,
    CorrelationRunEntry,
    DBService,
)


@pytest.fixture()
def db_service(tmp_path):
    return DBService(out_dir=tmp_path)


def test_db_service_persists_correlation_results(db_service):
    run_entry = CorrelationRunEntry(
        run_id="run-1",
        user_id=123,
        started_at=datetime(2024, 1, 1, 8, 0, 0),
        completed_at=datetime(2024, 1, 1, 8, 5, 0),
        window_days=7,
        config_json="{}",
    )
    db_service.add_correlation_run(run_entry)

    event_entry = CorrelationEventEntry(
        run_id="run-1",
        event_id="event-42",
        source="calendar",
        title="Team Sync",
        start=datetime(2024, 1, 1, 9, 0, 0),
        end=datetime(2024, 1, 1, 10, 0, 0),
    )
    db_service.add_correlation_event(event_entry)

    metric_entry = CorrelationMetricEntry(
        run_id="run-1",
        event_id="event-42",
        metric="stress",
        effect_size=18.5,
        effect_direction="increase",
        confidence=0.96,
        p_value=0.04,
        sample_count=10,
        baseline_mean=25.0,
        post_event_mean=43.5,
    )
    db_service.add_correlation_metric(metric_entry)

    with db_service._get_connection() as conn:
        run_rows = conn.execute("SELECT run_id, user_id FROM correlation_runs").fetchall()
        event_rows = conn.execute("SELECT event_id, title FROM correlation_events").fetchall()
        metric_rows = conn.execute("SELECT metric, effect_size, p_value FROM correlation_metric_effects").fetchall()

    assert run_rows == [("run-1", 123)]
    assert event_rows == [("event-42", "Team Sync")]
    assert metric_rows == [("stress", pytest.approx(18.5), pytest.approx(0.04))]


def test_correlation_metric_exists_detects_saved_metric(db_service):
    run_entry = CorrelationRunEntry(
        run_id="run-dup",
        user_id=123,
        started_at=datetime(2024, 1, 1, 8, 0, 0),
        completed_at=datetime(2024, 1, 1, 8, 5, 0),
        window_days=7,
        config_json="{}",
    )
    db_service.add_correlation_run(run_entry)

    event_entry = CorrelationEventEntry(
        run_id="run-dup",
        event_id="event-dup",
        source="calendar",
        title="Focus Block",
        start=datetime(2024, 1, 1, 9, 0, 0),
        end=datetime(2024, 1, 1, 10, 0, 0),
    )
    db_service.add_correlation_event(event_entry)

    metric_entry = CorrelationMetricEntry(
        run_id="run-dup",
        event_id="event-dup",
        metric="stress",
        effect_size=10.0,
        effect_direction="increase",
        confidence=0.9,
        p_value=0.05,
        sample_count=8,
    )
    db_service.add_correlation_metric(metric_entry)

    assert db_service.correlation_metric_exists(event_id="event-dup", metric="stress") is True
    assert db_service.correlation_metric_exists(event_id="event-dup", metric="hrv") is False


def test_fetch_correlation_events_returns_records(db_service):
    now = datetime.now(UTC)
    run_entry = CorrelationRunEntry(
        run_id="run-99",
        user_id=456,
        started_at=now - timedelta(hours=2),
        completed_at=now - timedelta(hours=1, minutes=30),
        window_days=7,
        config_json=json.dumps({"lookback_days": 7}),
    )
    db_service.add_correlation_run(run_entry)

    metadata_payload = json.dumps({"categories": ["focus"], "metadata": {"impact": "high"}})
    supporting_payload = json.dumps({"sleep_analysis": {"confidence": 0.92}})

    event_entry = CorrelationEventEntry(
        run_id="run-99",
        event_id="event-100",
        source="calendar",
        title="Deep Work Block",
        start=now - timedelta(hours=5),
        end=now - timedelta(hours=4),
        metadata_json=metadata_payload,
        supporting_json=supporting_payload,
    )
    db_service.add_correlation_event(event_entry)

    metric_entry = CorrelationMetricEntry(
        run_id="run-99",
        event_id="event-100",
        metric="stress",
        effect_size=12.5,
        effect_direction="increase",
        confidence=0.94,
        p_value=0.03,
        sample_count=8,
        baseline_mean=20.0,
        post_event_mean=32.5,
        notes="baseline elevated",
    )
    db_service.add_correlation_metric(metric_entry)

    records = db_service.fetch_correlation_events(lookback_days=3)
    assert records, "Expected at least one correlation record"
    record = records[0]
    assert record.event_id == "event-100"
    assert record.source == "calendar"
    assert record.categories == ("focus",)
    assert record.metadata == {"impact": "high"}
    assert record.supporting_evidence == {"sleep_analysis": {"confidence": 0.92}}
    assert record.run_config["lookback_days"] == 7
    assert record.metrics, "Expected metrics attached to correlation event"
    metric = record.metrics[0]
    assert metric.metric == "stress"
    assert metric.effect_direction == "increase"
    assert metric.effect_size == pytest.approx(12.5)


def test_fetch_metric_observations_returns_triggered_and_neutral(db_service):
    now = datetime.now(UTC)
    run_entry = CorrelationRunEntry(
        run_id="run-observations",
        user_id=7,
        started_at=now - timedelta(hours=1),
        completed_at=now,
        window_days=3,
        config_json="{}",
    )
    db_service.add_correlation_run(run_entry)

    event_entry = CorrelationEventEntry(
        run_id="run-observations",
        event_id="event-a",
        source="calendar",
        title="Focus Sprint",
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1, minutes=30),
    )
    db_service.add_correlation_event(event_entry)

    triggered_metric = CorrelationMetricEntry(
        run_id="run-observations",
        event_id="event-a",
        metric="stress",
        effect_size=9.0,
        effect_direction="increase",
        confidence=0.9,
        p_value=0.05,
        sample_count=6,
        is_triggered=True,
    )
    db_service.add_correlation_metric(triggered_metric)

    neutral_metric = CorrelationMetricEntry(
        run_id="run-observations",
        event_id="event-a",
        metric="body_battery",
        effect_size=1.2,
        effect_direction="neutral",
        confidence=0.5,
        p_value=0.5,
        sample_count=6,
        is_triggered=False,
    )
    db_service.add_correlation_metric(neutral_metric)

    observations = db_service.fetch_metric_observations(lookback_days=2)

    assert len(observations) == 2
    assert {obs.metric for obs in observations} == {"stress", "body_battery"}
    stress_obs = next(obs for obs in observations if obs.metric == "stress")
    assert stress_obs.is_triggered is True
    assert stress_obs.effect_size == pytest.approx(9.0)
    battery_obs = next(obs for obs in observations if obs.metric == "body_battery")
    assert battery_obs.is_triggered is False
    assert battery_obs.effect_size == pytest.approx(1.2)


def test_add_activity_variance_persists_entry(db_service):
    now = datetime.now(UTC)
    entry = ActivityImpactVarianceEntry(
        variance_id="var-1",
        run_id="run-1",
        event_id="event-1",
        title_key="focus-sprint",
        raw_title="Focus Sprint",
        metric="stress",
        window_start=now - timedelta(days=5),
        window_end=now,
        baseline_mean=5.0,
        baseline_stddev=2.5,
        baseline_sample_count=4,
        current_effect=9.5,
        delta=4.5,
        normalised_score=1.8,
        trend="increase",
        metadata_json=json.dumps({"categories": ["focus"]}),
        config_hash="hash-123",
    )

    db_service.add_activity_variance(entry)

    with db_service._get_connection() as conn:
        rows = conn.execute(
            "SELECT variance_id, metric, baseline_mean, normalised_score,"
            " config_hash FROM correlation_activity_variance"
        ).fetchall()

    assert rows == [("var-1", "stress", pytest.approx(5.0), pytest.approx(1.8), "hash-123")]


def test_activity_variance_exists_and_fetches_entry(db_service):
    now = datetime.now(UTC)
    entry = ActivityImpactVarianceEntry(
        variance_id="var-exists",
        run_id="run-123",
        event_id="event-123",
        title_key="focus-sprint",
        raw_title="Focus Sprint",
        metric="stress",
        window_start=now - timedelta(days=10),
        window_end=now,
        baseline_mean=4.0,
        baseline_stddev=1.5,
        baseline_sample_count=5,
        current_effect=7.5,
        delta=3.5,
        normalised_score=2.33,
        trend="increase",
        metadata_json=None,
        config_hash="cfg-hash",
    )
    db_service.add_activity_variance(entry)

    assert db_service.activity_variance_exists(event_id="event-123", metric="stress", config_hash="cfg-hash") is True

    fetched = db_service.get_activity_variance(event_id="event-123", metric="stress", config_hash="cfg-hash")
    assert fetched is not None
    assert fetched.variance_id == "var-exists"
    assert fetched.metric == "stress"
    assert fetched.config_hash == "cfg-hash"

    assert db_service.activity_variance_exists(event_id="event-123", metric="stress", config_hash="missing") is False


def test_fetch_activity_variances_respects_filters_and_ordering(db_service):
    now = datetime.now(UTC)

    entry_recent_high = ActivityImpactVarianceEntry(
        variance_id="var-1",
        run_id="run-variance",
        event_id="event-1",
        title_key="work-session",
        raw_title="Work Session",
        metric="stress",
        window_start=now - timedelta(days=5),
        window_end=now - timedelta(days=1),
        baseline_mean=10.0,
        baseline_stddev=2.0,
        baseline_sample_count=5,
        current_effect=20.0,
        delta=10.0,
        normalised_score=5.0,
        trend="increase",
        metadata_json=None,
        created_at=now - timedelta(hours=1),
        config_hash="hash",
    )

    entry_recent_low = ActivityImpactVarianceEntry(
        variance_id="var-2",
        run_id="run-variance",
        event_id="event-2",
        title_key="yoga",
        raw_title="Yoga",
        metric="stress",
        window_start=now - timedelta(days=4),
        window_end=now - timedelta(days=2),
        baseline_mean=12.0,
        baseline_stddev=3.0,
        baseline_sample_count=4,
        current_effect=9.0,
        delta=-3.0,
        normalised_score=-1.0,
        trend="decrease",
        metadata_json=None,
        created_at=now - timedelta(hours=2),
        config_hash="hash",
    )

    entry_out_of_range = ActivityImpactVarianceEntry(
        variance_id="var-3",
        run_id="run-variance",
        event_id="event-3",
        title_key="holiday",
        raw_title="Holiday",
        metric="stress",
        window_start=now - timedelta(days=10),
        window_end=now - timedelta(days=9),
        baseline_mean=8.0,
        baseline_stddev=1.0,
        baseline_sample_count=6,
        current_effect=6.0,
        delta=-2.0,
        normalised_score=-2.0,
        trend="decrease",
        metadata_json=None,
        created_at=now - timedelta(days=8),
        config_hash="hash",
    )

    db_service.add_activity_variance(entry_recent_high)
    db_service.add_activity_variance(entry_recent_low)
    db_service.add_activity_variance(entry_out_of_range)

    start_range = (now - timedelta(days=3)).date()
    end_range = now.date()

    results = db_service.fetch_activity_variances(
        start_date=start_range,
        end_date=end_range,
        limit=5,
        min_score=1.5,
    )

    assert len(results) == 1
    assert results[0].variance_id == "var-1"
    assert pytest.approx(results[0].normalised_score) == 5.0

    results_no_limit = db_service.fetch_activity_variances(
        start_date=start_range,
        end_date=end_range,
        limit=None,
        min_score=0.0,
    )

    assert [r.variance_id for r in results_no_limit] == ["var-1", "var-2"]
