from __future__ import annotations

from datetime import date

import pytest

from telegram_bot.service.life_context.garmin import GarminContextService


class FakeExporter:
    def __init__(self) -> None:
        self.refresh_calls: list[tuple[date, date | None]] = []
        self.export_calls: list[int] = []
        self.return_value = {"export": True}

    async def refresh_influxdb_data(self, start_date: date, end_date: date | None = None) -> None:
        self.refresh_calls.append((start_date, end_date))

    async def export_data(self, days: int):
        self.export_calls.append(days)
        return self.return_value


@pytest.mark.asyncio
async def test_get_window_refreshes_and_exports():
    exporter = FakeExporter()
    service = GarminContextService(exporter)

    result = await service.get_window(date(2024, 1, 1), date(2024, 1, 3))

    assert result == exporter.return_value
    assert exporter.refresh_calls == [(date(2024, 1, 1), date(2024, 1, 3))]
    assert exporter.export_calls == [3]


@pytest.mark.asyncio
async def test_get_window_validates_range():
    exporter = FakeExporter()
    service = GarminContextService(exporter)

    with pytest.raises(ValueError):
        await service.get_window(date(2024, 1, 5), date(2024, 1, 1))
