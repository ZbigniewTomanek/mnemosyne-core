from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from telegram_bot.service.calendar_service.models import CalendarEvent, CalendarEventsResult
from telegram_bot.service.correlation_engine.models import (
    BioSignalType,
    CorrelationEvent,
    CorrelationJobConfig,
    CorrelationRunRequest,
    MetricThreshold,
    TimeSeriesPoint,
    WindowConfig,
)
from telegram_bot.service.correlation_engine.sources import (
    CalendarEventSource,
    GarminExportDataCache,
    InfluxMetricSource,
)
from telegram_bot.service.influxdb_garmin_data_exporter import GarminExportData


class StubCalendarService:
    def __init__(self, events_result: CalendarEventsResult):
        self._result = events_result

    async def get_events(self, query=None):  # noqa: D401 - simple stub
        return self._result


def _make_calendar_event(start: datetime, end: datetime, calendar_name: str = "Work") -> CalendarEvent:
    return CalendarEvent(
        title="Team Sync",
        start_date=start,
        end_date=end,
        calendar_name=calendar_name,
        location="Zoom",
        notes="Weekly sync",
        is_all_day=False,
    )


@pytest.mark.asyncio
async def test_calendar_event_source_filters_and_transforms():
    tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    within_range_start = now - timedelta(days=2)
    within_range_end = within_range_start + timedelta(hours=1)
    old_start = now - timedelta(days=20)
    old_end = old_start + timedelta(hours=1)

    events_result = CalendarEventsResult(
        events=[
            _make_calendar_event(within_range_start, within_range_end, "Work"),
            _make_calendar_event(old_start, old_end, "Personal"),
        ],
        reminders=[],
        query_start_date=within_range_start.date(),
        query_end_date=now.date(),
        total_count=2,
        reminder_count=0,
        calendars_queried=["Work", "Personal"],
    )

    source = CalendarEventSource(StubCalendarService(events_result), tz=tz)
    config = CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        metrics={BioSignalType.STRESS: MetricThreshold()},
        windows=WindowConfig(),
    )

    events = await source.fetch_events(config)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, CorrelationEvent)
    assert event.title == "Team Sync"
    assert event.source == "calendar"
    assert "Work" in event.categories
    assert event.start == within_range_start
    assert event.end == within_range_end


class StubExporter:
    def __init__(self, data: GarminExportData):
        self._data = data
        self.calls: list[int] = []

    async def export_data(self, days: int = 7):
        self.calls.append(days)
        return self._data


@pytest.mark.asyncio
async def test_influx_metric_source_provides_resampled_points():
    tz = ZoneInfo("UTC")
    now = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
    baseline_times = [now - timedelta(minutes=20) + timedelta(minutes=5 * i) for i in range(4)]
    effect_times = [now + timedelta(minutes=5 * i) for i in range(4)]
    baseline_values = [20, 22, 21, 23]
    effect_values = [30, 32, 31, 33]

    df = pd.DataFrame(
        {
            "time": baseline_times + effect_times,
            "stressLevel": baseline_values + effect_values,
        }
    )

    exporter = StubExporter(GarminExportData(stress_intraday=df))
    cache = GarminExportDataCache(exporter=exporter)
    source = InfluxMetricSource(cache=cache, tz=tz)

    window = WindowConfig(baseline=timedelta(minutes=20), post_event=timedelta(minutes=15), sampling_freq="5min")
    job_config = CorrelationJobConfig(
        lookback_days=2,
        timezone="UTC",
        metrics={BioSignalType.STRESS: MetricThreshold(min_samples=3)},
        windows=window,
    )
    event = CorrelationEvent(
        id=str(uuid4()),
        title="Team Sync",
        start=now,
        end=now + timedelta(minutes=5),
        source="calendar",
    )
    request = CorrelationRunRequest(user_id=1, config=job_config, events=[event])

    await source.prepare(request)
    series = await source.fetch_series(
        metric=BioSignalType.STRESS,
        start=event.start - window.baseline,
        end=event.end + window.post_event,
        sample_frequency=window.sampling_freq,
    )

    assert exporter.calls, "Exporter should be invoked to load data"
    assert series, "Should return interpolated time series"
    assert all(isinstance(point, TimeSeriesPoint) for point in series)
    assert series[0].ts.tzinfo is not None
    assert min(point.ts for point in series) >= event.start - window.baseline
    assert max(point.ts for point in series) <= event.end + window.post_event
