from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram_bot.service.influxdb_garmin_data_exporter import GarminExportData, InfluxDBGarminDataExporter


class GarminContextService:
    """Thin wrapper around the InfluxDB exporter for date-window fetches."""

    def __init__(self, exporter: InfluxDBGarminDataExporter) -> None:
        self._exporter = exporter

    async def get_window(self, start_date: date, end_date: date) -> GarminExportData:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        await self._exporter.refresh_influxdb_data(start_date=start_date, end_date=end_date)
        days = (end_date - start_date).days + 1
        return await self._exporter.export_data(days=days)
