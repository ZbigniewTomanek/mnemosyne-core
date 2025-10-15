from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from telegram_bot.service.calendar_service.calendar_service import CalendarService
from telegram_bot.service.calendar_service.models import CalendarEvent as CalendarEventModel, CalendarEventQuery
from telegram_bot.service.correlation_engine.models import (
    BioSignalType,
    CorrelationEvent,
    CorrelationJobConfig,
    CorrelationRunRequest,
    GarminActivitySourceConfig,
    TimeSeriesPoint,
)
from telegram_bot.service.influxdb_garmin_data_exporter import GarminExportData, InfluxDBGarminDataExporter


def _time_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in ["time", "Time", "timestamp", "Timestamp", "_time", "startTime", "measurement_time"]:
        if candidate in df.columns:
            return candidate
    return None


def _activity_id_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in ["Activity_ID", "ActivityID", "ActivityId", "activityId"]:
        if candidate in df.columns:
            return candidate
    return None


@dataclass
class _MetricFrameSpec:
    attr_name: str
    value_candidates: tuple[str, ...]


_METRIC_SPECS: dict[BioSignalType, _MetricFrameSpec] = {
    BioSignalType.STRESS: _MetricFrameSpec("stress_intraday", ("stressLevel", "value", "Stress")),
    BioSignalType.BODY_BATTERY: _MetricFrameSpec("body_battery_intraday", ("BodyBatteryLevel", "bodyBattery", "value")),
    BioSignalType.HEART_RATE: _MetricFrameSpec("heart_rate_intraday", ("HeartRate", "heartRate", "value")),
    BioSignalType.BREATHING_RATE: _MetricFrameSpec(
        "breathing_rate_intraday", ("BreathingRate", "respirationValue", "value")
    ),
    BioSignalType.SLEEP: _MetricFrameSpec("sleep_summary", ("sleepScore", "sleepTimeSeconds", "SleepScore")),
}


class CalendarEventSource:
    """Fetches calendar events and adapts them to correlation engine events."""

    def __init__(
        self,
        calendar_service: CalendarService,
        tz: ZoneInfo,
        calendar_filters: Optional[Iterable[str]] = None,
    ) -> None:
        self._calendar_service = calendar_service
        self._tz = tz
        self._calendar_filters = list(calendar_filters) if calendar_filters else None

    async def fetch_events(self, job_config: CorrelationJobConfig) -> list[CorrelationEvent]:
        source_config = job_config.sources.calendar
        if not source_config.enabled:
            logger.info("Calendar event source disabled via configuration")
            return []

        now = datetime.now(self._tz)
        lookback_start = (now - timedelta(days=job_config.lookback_days)).date()
        lookahead_end = now.date()

        calendar_filters = (
            source_config.calendar_filters if source_config.calendar_filters is not None else self._calendar_filters
        )

        query = CalendarEventQuery(
            start_date=lookback_start,
            end_date=lookahead_end,
            include_reminders=False,
            calendar_names=calendar_filters,
            include_all_day=False,
        )

        result = await self._calendar_service.get_events(query)

        events: list[CorrelationEvent] = []
        cutoff = datetime.now(self._tz) - timedelta(days=job_config.lookback_days)

        for raw_event in result.events:
            if raw_event.end_date < cutoff:
                continue
            events.append(self._to_correlation_event(raw_event))

        events.sort(key=lambda event: event.start)

        logger.info(
            "Fetched calendar events",
            count=len(events),
            lookback_start=lookback_start,
            filters=calendar_filters,
        )

        return events

    def _to_correlation_event(self, event: CalendarEventModel) -> CorrelationEvent:
        event_id_source = (
            f"{event.calendar_name}|{event.title}|{event.start_date.isoformat()}|{event.end_date.isoformat()}"
        )
        event_id = hashlib.sha256(event_id_source.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        categories = {event.calendar_name}
        metadata = {}
        if event.location:
            metadata["location"] = event.location
        if event.notes:
            metadata["notes"] = event.notes

        return CorrelationEvent(
            id=event_id,
            title=event.title,
            start=event.start_date,
            end=event.end_date,
            source="calendar",
            categories=categories,
            metadata=metadata,
        )


class GarminExportDataCache:
    """Shared cache for Garmin exports to avoid redundant fetches."""

    def __init__(self, exporter: InfluxDBGarminDataExporter, cache_timeout_hours: int = 1) -> None:
        self._exporter = exporter
        self._export: Optional[GarminExportData] = None
        self._loaded_days: int = 0
        self._latest_loaded_at: Optional[datetime] = None
        self._cache_timeout_hours = cache_timeout_hours
        self._lock = asyncio.Lock()

    async def ensure_export(self, days: int) -> tuple[GarminExportData, bool]:
        async with self._lock:
            cache_valid = (
                self._export is not None
                and self._loaded_days >= days
                and self._latest_loaded_at
                and (datetime.now(UTC) - self._latest_loaded_at) < timedelta(hours=self._cache_timeout_hours)
            )
            if cache_valid:
                # Type assertion: cache_valid is only True when self._export is not None
                assert self._export is not None
                return self._export, False

            logger.info("Exporting Garmin data", days=days)
            export = await self._exporter.export_data(days=days)
            self._export = export
            self._loaded_days = days
            self._latest_loaded_at = datetime.now(UTC)
            return export, True

    def clear(self) -> None:
        self._export = None
        self._loaded_days = 0
        self._latest_loaded_at = None


class InfluxMetricSource:
    """Loads Garmin intraday metrics from InfluxDB exporter data."""

    def __init__(self, cache: GarminExportDataCache, tz: ZoneInfo) -> None:
        self._cache = cache
        self._tz = tz
        self._frames: dict[BioSignalType, pd.DataFrame] = {}
        self._loaded_days: int = 0

    async def prepare(self, request: CorrelationRunRequest) -> None:
        earliest_event = min((event.start for event in request.events), default=datetime.now(self._tz))
        days_needed = max(
            request.config.lookback_days, int((datetime.now(UTC) - earliest_event.astimezone(UTC)).days) + 2
        )
        await self._ensure_data(days_needed)

    def clear_cache(self) -> None:
        """Clear cached metric frames to free memory."""
        logger.debug("Clearing metric source cache ({} metrics loaded)", len(self._frames))
        self._frames.clear()
        self._loaded_days = 0

    async def _ensure_data(self, days: int) -> None:
        export, refreshed = await self._cache.ensure_export(days)
        if not refreshed and self._frames and self._loaded_days >= days:
            return

        self._frames = self._build_frames(export)
        self._loaded_days = days

    async def fetch_series(
        self,
        metric: BioSignalType,
        start: datetime,
        end: datetime,
        sample_frequency: str,
    ) -> list[TimeSeriesPoint]:
        frame = self._frames.get(metric)
        if frame is None or frame.empty:
            return []

        window = frame[(frame["ts"] >= start) & (frame["ts"] <= end)].copy()
        if window.empty:
            return []

        window.set_index("ts", inplace=True)
        window = window.sort_index()

        try:
            resampled = window.resample(sample_frequency).mean().interpolate(limit_direction="both")
        except ValueError as e:
            logger.warning(
                "Invalid sampling frequency '{}', using raw data instead. Error: {}. "
                "Valid examples: '1min', '5min', '1h'",
                sample_frequency,
                str(e),
            )
            resampled = window

        resampled = resampled.reset_index()
        return [TimeSeriesPoint(ts=row["ts"], value=float(row["value"])) for _, row in resampled.iterrows()]

    def _build_frames(self, export: GarminExportData) -> dict[BioSignalType, pd.DataFrame]:
        logger.info("Building metric frames from Garmin export", metrics=[m.value for m in _METRIC_SPECS.keys()])
        frames: dict[BioSignalType, pd.DataFrame] = {}
        for metric, spec in _METRIC_SPECS.items():
            raw_frame = getattr(export, spec.attr_name)
            frames[metric] = self._normalize_frame(raw_frame, spec.value_candidates)
            if frames[metric].empty:
                logger.warning("No data available for metric", metric=metric.value)
            else:
                logger.debug(
                    "Loaded metric data",
                    metric=metric.value,
                    rows=len(frames[metric]),
                    time_range=f"{frames[metric]['ts'].min()} to {frames[metric]['ts'].max()}",
                )
        return frames

    def _normalize_frame(self, frame: Optional[pd.DataFrame], value_candidates: tuple[str, ...]) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["ts", "value"])

        df = frame.copy()
        time_col = _time_column(df)
        if not time_col:
            logger.warning("No time column detected in Garmin export frame. Available columns: {}", list(df.columns))
            return pd.DataFrame(columns=["ts", "value"])

        value_col = next((col for col in value_candidates if col in df.columns), None)
        if value_col is None:
            logger.warning("No value column found for metric candidates {}", value_candidates)
            return pd.DataFrame(columns=["ts", "value"])

        df = df[[time_col, value_col]].rename(columns={time_col: "ts", value_col: "value"})
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts", "value"])

        # Filter Garmin sentinel values (-3, -2, -1) used for "no data" or "resting state"
        initial_count = len(df)
        df = df[df["value"] >= 0]
        filtered_count = initial_count - len(df)
        if filtered_count > 0:
            logger.debug("Filtered {} Garmin sentinel values (negative values) from metric data", filtered_count)

        if df.empty:
            return pd.DataFrame(columns=["ts", "value"])

        df = df.sort_values("ts").drop_duplicates(subset="ts")
        df["ts"] = df["ts"].dt.tz_convert(self._tz)
        return df


class GarminActivityEventSource:
    """Creates correlation events from Garmin activity summaries."""

    _ALIAS_COLUMNS: dict[str, tuple[str, ...]] = {
        "activityName": ("activityName", "ActivityName"),
        "activityType": ("activityType", "ActivityType"),
        "distance": ("distance", "Distance"),
        "elapsedDuration": ("elapsedDuration", "ElapsedDuration"),
        "movingDuration": ("movingDuration", "MovingDuration"),
        "calories": ("calories", "Calories"),
        "averageHR": ("averageHR", "AverageHR"),
        "maxHR": ("maxHR", "MaxHR"),
        "hrZone4Seconds": ("hrZone4Seconds", "hrTimeInZone_4"),
        "hrZone5Seconds": ("hrZone5Seconds", "hrTimeInZone_5"),
        "Aerobic_Training": ("Aerobic_Training",),
        "Anaerobic_Training": ("Anaerobic_Training",),
        "Sport": ("Sport",),
        "Sub_Sport": ("Sub_Sport", "SubSport"),
        "locationName": ("locationName", "Location", "LocationName"),
    }

    def __init__(self, cache: GarminExportDataCache, tz: ZoneInfo) -> None:
        self._cache = cache
        self._tz = tz

    async def fetch_events(self, job_config: CorrelationJobConfig) -> list[CorrelationEvent]:
        source_config = job_config.sources.garmin_activity
        if not source_config.enabled:
            logger.info("Garmin activity event source disabled via configuration")
            return []

        export, _ = await self._cache.ensure_export(job_config.lookback_days + 1)
        summary = getattr(export, "activity_summary", None)
        if summary is None or summary.empty:
            logger.info("No Garmin activity summary data available")
            return []

        df = summary.copy()
        time_col = _time_column(df)
        id_col = _activity_id_column(df)
        if not time_col or not id_col:
            logger.warning(
                "Activity summary missing required columns",
                time_col=time_col,
                id_col=id_col,
            )
            return []

        df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
        df = df.dropna(subset=[time_col, id_col])
        df[time_col] = df[time_col].dt.tz_convert(self._tz)

        cutoff = datetime.now(self._tz) - timedelta(days=job_config.lookback_days)
        df = df[df[time_col] >= cutoff]
        if df.empty:
            logger.info("No Garmin activities within lookback window", lookback_days=job_config.lookback_days)
            return []

        df = self._enrich_with_sessions(export, df, id_col)
        df = self._apply_activity_filters(df, source_config)
        if df.empty:
            logger.info("No Garmin activities passed filtering thresholds")
            return []

        df = df.drop_duplicates(subset=[id_col], keep="last")

        events: list[CorrelationEvent] = []
        for _, row in df.iterrows():
            event = self._row_to_event(
                row,
                id_col=id_col,
                time_col=time_col,
                metadata_fields=source_config.metadata_fields,
            )
            if event is not None:
                events.append(event)

        events.sort(key=lambda evt: evt.start)
        logger.info("Emitting Garmin activity correlation events", count=len(events))
        return events

    def _enrich_with_sessions(self, export: GarminExportData, df: pd.DataFrame, id_col: str) -> pd.DataFrame:
        session = getattr(export, "activity_session", None)
        if session is None or session.empty:
            return df

        session_df = session.copy()
        session_id_col = _activity_id_column(session_df)
        if not session_id_col:
            return df

        desired = [
            col for col in ["Aerobic_Training", "Anaerobic_Training", "Sport", "Sub_Sport"] if col in session_df.columns
        ]
        if not desired:
            return df

        session_subset = (
            session_df[[session_id_col] + desired]
            .drop_duplicates(subset=[session_id_col], keep="last")
            .rename(columns={session_id_col: id_col})
        )
        merged = df.merge(session_subset, how="left", on=id_col)
        return merged

    def _apply_activity_filters(self, df: pd.DataFrame, config: GarminActivitySourceConfig) -> pd.DataFrame:
        filtered = df.copy()

        required_columns = ["elapsedDuration", "movingDuration"]
        for column in required_columns:
            if column not in filtered.columns:
                filtered[column] = 0.0
            filtered[column] = pd.to_numeric(filtered[column], errors="coerce").fillna(0.0)

        min_duration_seconds = config.min_duration_minutes * 60
        filtered = filtered[filtered["elapsedDuration"] >= min_duration_seconds]
        filtered = filtered[filtered["elapsedDuration"] > 0]

        filtered["_moving_ratio"] = 0.0
        nonzero = filtered["elapsedDuration"] > 0
        filtered.loc[nonzero, "_moving_ratio"] = (
            filtered.loc[nonzero, "movingDuration"] / filtered.loc[nonzero, "elapsedDuration"]
        )
        filtered = filtered[filtered["_moving_ratio"] >= config.min_moving_ratio]

        zone4 = pd.to_numeric(filtered.get("hrTimeInZone_4"), errors="coerce").fillna(0.0)
        zone5 = pd.to_numeric(filtered.get("hrTimeInZone_5"), errors="coerce").fillna(0.0)
        filtered["_zone45"] = zone4 + zone5
        filtered = filtered[filtered["_zone45"] >= config.min_hr_zone45_seconds]

        include = {sport.lower() for sport in config.include_sports} if config.include_sports else None
        exclude = {sport.lower() for sport in config.exclude_sports} if config.exclude_sports else set()

        if include is not None or exclude:
            # Vectorized sport filtering: create sport_key column from Sport, Sub_Sport, or activityType
            filtered["_sport_key"] = (
                filtered.get("Sport", pd.Series(index=filtered.index, dtype=str))
                .fillna(filtered.get("Sub_Sport", pd.Series(index=filtered.index, dtype=str)))
                .fillna(filtered.get("activityType", pd.Series(index=filtered.index, dtype=str)))
                .str.lower()
            )

            if include is not None:
                filtered = filtered[filtered["_sport_key"].isin(include)]

            if exclude:
                filtered = filtered[~filtered["_sport_key"].isin(exclude)]

            filtered = filtered.drop(columns=["_sport_key"])

        return filtered.drop(columns=[col for col in ["_moving_ratio", "_zone45"] if col in filtered.columns])

    def _row_to_event(
        self,
        row: pd.Series,
        *,
        id_col: str,
        time_col: str,
        metadata_fields: Iterable[str],
    ) -> Optional[CorrelationEvent]:
        start = row.get(time_col)
        if not isinstance(start, datetime):
            return None

        elapsed_seconds = float(row.get("elapsedDuration", 0.0) or 0.0)
        end = start + timedelta(seconds=elapsed_seconds)
        event_id = str(row.get(id_col))
        if not event_id:
            return None

        metadata: dict[str, Any] = {}
        for field in metadata_fields:
            value = self._resolve_field(row, field)
            if value is None:
                continue
            metadata[field] = value

        categories = {
            sport
            for sport in [
                row.get("activityType"),
                row.get("Sport"),
                row.get("Sub_Sport"),
            ]
            if isinstance(sport, str) and sport
        }

        title = metadata.get("activityName") or f"Garmin Activity {event_id}"
        return CorrelationEvent(
            id=event_id,
            title=str(title),
            start=start,
            end=end,
            source="garmin_activity",
            categories=categories,
            metadata=metadata,
        )

    def _resolve_field(self, row: pd.Series, field: str) -> Optional[Any]:
        aliases = self._ALIAS_COLUMNS.get(field, (field,))
        for alias in aliases:
            if alias in row and not pd.isna(row[alias]):
                value = row[alias]
                if isinstance(value, (float, int)):
                    return float(value)
                return value
        return None
