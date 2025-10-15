"""Sleep correlation helpers for pairing events with Garmin sleep sessions."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from telegram_bot.service.correlation_engine.models import (
    CorrelationEvent,
    CorrelationRunRequest,
    SleepCorrelationConfig,
)
from telegram_bot.service.correlation_engine.sources import GarminExportDataCache
from telegram_bot.service.influxdb_garmin_data_exporter import GarminExportData


@dataclass(slots=True)
class SleepSession:
    start: datetime
    end: datetime
    is_main_sleep: bool
    metrics: dict[str, float]

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass(slots=True)
class SleepMatch:
    event: CorrelationEvent
    matched_session: SleepSession
    baseline_sessions: list[SleepSession]


class SleepSessionMatcher:
    """Pairs events with the first qualifying sleep session and builds baselines."""

    def __init__(self, sessions: Iterable[SleepSession]):
        self._sessions = sorted(sessions, key=lambda session: session.end)

    def match_event(self, event: CorrelationEvent, config: SleepCorrelationConfig) -> Optional[SleepMatch]:
        if not config.enabled:
            return None

        candidate = self._find_candidate(event, config)
        if candidate is None:
            return None

        baseline = self._baseline_sessions(candidate, config)
        return SleepMatch(event=event, matched_session=candidate, baseline_sessions=baseline)

    def _find_candidate(self, event: CorrelationEvent, config: SleepCorrelationConfig) -> Optional[SleepSession]:
        lookahead_end = event.end + timedelta(hours=config.lookahead_hours)

        for session in self._sessions:
            if session.end < event.end:
                continue
            if session.end > lookahead_end:
                break
            if not self._qualifies(session, config):
                continue
            return session
        return None

    def _baseline_sessions(self, matched: SleepSession, config: SleepCorrelationConfig) -> list[SleepSession]:
        candidates: list[SleepSession] = []
        for session in reversed(self._sessions):
            if session.end > matched.start:
                continue
            if not self._qualifies(session, config):
                continue
            candidates.append(session)
            if len(candidates) >= config.baseline_nights:
                break

        return list(reversed(candidates))

    @staticmethod
    def _qualifies(session: SleepSession, config: SleepCorrelationConfig) -> bool:
        if config.main_sleep_only and not session.is_main_sleep:
            return False
        if session.duration_minutes < config.min_sleep_duration_minutes:
            return False
        return True


_SLEEP_START_CANDIDATES: tuple[str, ...] = (
    "sleepStartTimestampGMT",
    "sleepStartTimestamp",
    "startTimeGMT",
    "startTime",
    "SleepStartTime",
)

_SLEEP_END_CANDIDATES: tuple[str, ...] = (
    "sleepEndTimestampGMT",
    "sleepEndTimestamp",
    "endTimeGMT",
    "endTime",
    "SleepEndTime",
)

_SLEEP_DURATION_CANDIDATES: tuple[str, ...] = (
    "sleepTimeSeconds",
    "durationInSeconds",
    "duration",
)

SLEEP_METRIC_FIELDS: tuple[str, ...] = (
    "sleepScore",
    "sleepTimeSeconds",
    "deepSleepSeconds",
    "remSleepSeconds",
    "avgOvernightHrv",
    "avgSleepStress",
    "bodyBatteryChange",
    "restingHeartRate",
)


def build_sleep_sessions(export: GarminExportData, tz: ZoneInfo) -> list[SleepSession]:
    summary = getattr(export, "sleep_summary", None)
    if summary is None or summary.empty:
        return []

    df = summary.copy()
    sessions: list[SleepSession] = []

    for _, row in df.iterrows():
        start = _extract_time(row, _SLEEP_START_CANDIDATES, tz)
        end = _extract_time(row, _SLEEP_END_CANDIDATES, tz)

        # Skip if both timestamps are missing
        if start is None and end is None:
            continue

        # Infer missing timestamp from duration if available
        if start is None and end is not None:
            duration = _extract_duration(row)
            if duration is None:
                continue
            start = end - timedelta(seconds=duration)
        elif start is not None and end is None:
            duration = _extract_duration(row)
            if duration is None:
                continue
            end = start + timedelta(seconds=duration)

        # At this point, both start and end are guaranteed to be non-None
        # Type assertions to help mypy understand the flow
        assert start is not None
        assert end is not None

        metrics = _extract_metrics(row, SLEEP_METRIC_FIELDS)
        is_main_sleep = _is_main_sleep(row)

        sessions.append(
            SleepSession(
                start=start,
                end=end,
                is_main_sleep=is_main_sleep,
                metrics=metrics,
            )
        )

    sessions.sort(key=lambda session: session.start)
    return sessions


def serialize_session(session: SleepSession, metric_keys: Sequence[str] | None = None) -> dict[str, Any]:
    keys = metric_keys or SLEEP_METRIC_FIELDS
    return {
        "start": session.start.isoformat(),
        "end": session.end.isoformat(),
        "is_main_sleep": session.is_main_sleep,
        "duration_minutes": round(session.duration_minutes, 2),
        "metrics": {key: session.metrics.get(key) for key in keys if key in session.metrics},
    }


class SleepAnalysisService:
    """Access layer for Garmin sleep sessions used in correlation analysis."""

    def __init__(self, cache: GarminExportDataCache, tz: ZoneInfo) -> None:
        self._cache = cache
        self._tz = tz
        self._sessions: list[SleepSession] = []
        self._loaded_days: int = 0
        self._matcher: Optional[SleepSessionMatcher] = None

    async def prepare(self, request: CorrelationRunRequest) -> None:
        if not request.config.sleep_analysis.enabled:
            self._matcher = None
            return

        days_needed = max(
            request.config.lookback_days,
            request.config.sleep_analysis.baseline_nights + request.config.lookback_days,
        )
        export, refreshed = await self._cache.ensure_export(days=days_needed + 2)
        if refreshed or self._loaded_days < days_needed or self._matcher is None:
            self._sessions = build_sleep_sessions(export, self._tz)
            self._matcher = SleepSessionMatcher(self._sessions)
            self._loaded_days = days_needed

    def match_event(self, event: CorrelationEvent, config: SleepCorrelationConfig) -> Optional[SleepMatch]:
        if self._matcher is None:
            return None
        return self._matcher.match_event(event, config)

    def serialize_sessions(self, sessions: Sequence[SleepSession]) -> list[dict[str, Any]]:
        return [serialize_session(session) for session in sessions]


def _extract_time(row: pd.Series, candidates: Sequence[str], tz: ZoneInfo) -> Optional[datetime]:
    for column in candidates:
        if column not in row or pd.isna(row[column]):
            continue
        value = pd.to_datetime(row[column], utc=True, errors="coerce")
        if pd.isna(value):
            continue
        if value.tzinfo is None:
            value = value.tz_localize("UTC")
        return value.tz_convert(tz)
    return None


def _extract_duration(row: pd.Series) -> Optional[float]:
    for column in _SLEEP_DURATION_CANDIDATES:
        if column not in row or pd.isna(row[column]):
            continue
        try:
            return float(row[column])
        except (TypeError, ValueError):
            continue
    return None


def _extract_metrics(row: pd.Series, metric_fields: Sequence[str]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for field in metric_fields:
        if field not in row or pd.isna(row[field]):
            continue
        try:
            metrics[field] = float(row[field])
        except (TypeError, ValueError):
            continue
    return metrics


def _is_main_sleep(row: pd.Series) -> bool:
    if "isMainSleep" in row and not pd.isna(row["isMainSleep"]):
        return bool(row["isMainSleep"])
    if "mainSleep" in row and not pd.isna(row["mainSleep"]):
        return bool(row["mainSleep"])
    if "sleepWindowType" in row and not pd.isna(row["sleepWindowType"]):
        value = str(row["sleepWindowType"]).lower()
        if "main" in value:
            return True
        if "nap" in value:
            return False
    if "isNap" in row and not pd.isna(row["isNap"]):
        return not bool(row["isNap"])
    return True
