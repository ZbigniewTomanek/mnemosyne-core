from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from telegram_bot.service.correlation_engine.models import CorrelationEvent, SleepCorrelationConfig
from telegram_bot.service.correlation_engine.sleep import SleepSession, SleepSessionMatcher


def _session(days_offset: int, start_hour: int, duration_hours: float, *, main_sleep: bool = True, score: float = 75.0):
    start = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=days_offset, hours=start_hour)
    end = start + timedelta(hours=duration_hours)
    return SleepSession(
        start=start,
        end=end,
        is_main_sleep=main_sleep,
        metrics={
            "sleepScore": score,
            "sleepTimeSeconds": duration_hours * 3600,
            "deepSleepSeconds": 60 * 90,
            "avgOvernightHrv": 45.0,
            "avgSleepStress": 18.0,
            "bodyBatteryChange": 25.0,
            "restingHeartRate": 48.0,
        },
    )


@pytest.mark.asyncio
async def test_sleep_matcher_finds_first_session_within_lookahead_and_builds_baseline():
    event = CorrelationEvent(
        id="cal-1",
        title="Hard Workout",
        start=datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
        end=datetime(2024, 1, 2, 19, 30, tzinfo=UTC),
        source="garmin_activity",
    )

    sessions = [
        _session(-5, 22, 7),
        _session(-4, 22, 7),
        _session(-3, 22, 7),
        _session(-2, 22, 7),
        _session(-1, 22, 7),
        _session(0, 1, 1, main_sleep=False),
        _session(0, 23, 7, score=60.0),
        _session(1, 23, 7, score=62.0),
    ]

    matcher = SleepSessionMatcher(sessions)
    config = SleepCorrelationConfig(baseline_nights=5, lookahead_hours=36, main_sleep_only=True)

    match = matcher.match_event(event, config)

    assert match is not None, "Expected a sleep match"
    assert match.event.id == event.id
    assert match.matched_session.start == datetime(2024, 1, 2, 23, 0, tzinfo=UTC)
    assert len(match.baseline_sessions) == 5
    assert all(session.end <= match.matched_session.start for session in match.baseline_sessions)


@pytest.mark.asyncio
async def test_sleep_matcher_respects_main_sleep_flag_and_duration():
    event = CorrelationEvent(
        id="cal-2",
        title="Evening Party",
        start=datetime(2024, 1, 2, 20, 0, tzinfo=UTC),
        end=datetime(2024, 1, 2, 22, 0, tzinfo=UTC),
        source="garmin_activity",
    )

    sessions = [
        _session(0, 1, 2, main_sleep=False),
        _session(0, 5, 3, main_sleep=False),
        _session(0, 23, 3.5, main_sleep=True),
    ]

    matcher = SleepSessionMatcher(sessions)
    config = SleepCorrelationConfig(
        baseline_nights=3,
        lookahead_hours=36,
        main_sleep_only=True,
        min_sleep_duration_minutes=240,
    )

    match = matcher.match_event(event, config)

    assert match is None, "No sleep session meets minimum duration requirement"
