from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from telegram_bot.service.correlation_engine.models import (
    CorrelationJobConfig,
    CorrelationSourcesConfig,
    GarminActivitySourceConfig,
)
from telegram_bot.service.correlation_engine.sources import GarminActivityEventSource
from telegram_bot.service.influxdb_garmin_data_exporter import GarminExportData


class StubCache:
    def __init__(self, export: GarminExportData):
        self._export = export
        self.calls: list[int] = []

    async def ensure_export(self, days: int):  # noqa: D401 - testing stub
        self.calls.append(days)
        return self._export, False


def _job_config(activity_config: GarminActivitySourceConfig) -> CorrelationJobConfig:
    sources = CorrelationSourcesConfig(garmin_activity=activity_config)
    return CorrelationJobConfig(
        lookback_days=7,
        timezone="UTC",
        sources=sources,
    )


@pytest.mark.asyncio
async def test_activity_source_filters_by_thresholds_and_populates_metadata():
    now = datetime.now(UTC)
    df = pd.DataFrame(
        [
            {
                "time": now - timedelta(hours=1),
                "Activity_ID": "100",
                "activityName": "Tempo Run",
                "activityType": "running",
                "elapsedDuration": 3600,
                "movingDuration": 3000,
                "distance": 10000,
                "calories": 800,
                "averageHR": 150,
                "maxHR": 180,
                "hrTimeInZone_4": 400,
                "hrTimeInZone_5": 120,
                "Sport": "Running",
                "Sub_Sport": "Road Running",
                "locationName": "Warsaw",
            },
            {
                # Short activity should be filtered out
                "time": now - timedelta(hours=2),
                "Activity_ID": "101",
                "activityName": "Easy Ride",
                "activityType": "cycling",
                "elapsedDuration": 600,
                "movingDuration": 400,
                "distance": 2000,
                "calories": 150,
                "averageHR": 120,
                "maxHR": 140,
                "hrTimeInZone_4": 30,
                "hrTimeInZone_5": 10,
                "Sport": "Cycling",
            },
        ]
    )

    cache = StubCache(GarminExportData(activity_summary=df))
    source = GarminActivityEventSource(cache=cache, tz=ZoneInfo("UTC"))

    config = GarminActivitySourceConfig(metadata_fields=["activityName", "distance", "hrZone4Seconds"])
    job_config = _job_config(config)

    events = await source.fetch_events(job_config)

    assert len(events) == 1
    event = events[0]
    assert event.id == "100"
    assert event.metadata["activityName"] == "Tempo Run"
    assert event.metadata["distance"] == pytest.approx(10000)
    assert event.metadata["hrZone4Seconds"] == pytest.approx(400.0)
    assert "Running" in event.categories


@pytest.mark.asyncio
async def test_activity_source_respects_include_and_exclude_lists():
    now = datetime.now(UTC)
    df = pd.DataFrame(
        [
            {
                "time": now - timedelta(hours=1),
                "Activity_ID": "200",
                "activityName": "Strength",
                "activityType": "strength_training",
                "elapsedDuration": 3600,
                "movingDuration": 3200,
                "hrTimeInZone_4": 500,
                "hrTimeInZone_5": 100,
                "Sport": "Strength",
            }
        ]
    )

    cache = StubCache(GarminExportData(activity_summary=df))
    source = GarminActivityEventSource(cache=cache, tz=ZoneInfo("UTC"))

    config = GarminActivitySourceConfig(
        include_sports={"running"},
        metadata_fields=["activityType"],
    )
    job_config = _job_config(config)

    events = await source.fetch_events(job_config)
    assert events == []

    config = GarminActivitySourceConfig(
        exclude_sports={"strength"},
        metadata_fields=["activityType"],
    )
    job_config = _job_config(config)
    events = await source.fetch_events(job_config)
    assert events == []
