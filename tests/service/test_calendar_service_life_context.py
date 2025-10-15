from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from telegram_bot.service.calendar_service.calendar_service import CalendarBackend, CalendarConfig, CalendarService
from telegram_bot.service.calendar_service.models import CalendarEvent, CalendarEventQuery, CalendarEventsResult


class DummyBackend(CalendarBackend):
    def __init__(self, result: CalendarEventsResult) -> None:
        self.result = result
        self.queries: list[CalendarEventQuery] = []

    async def get_events(self, query: CalendarEventQuery, config: CalendarConfig) -> CalendarEventsResult:
        self.queries.append(query)
        return self.result


@pytest.mark.asyncio
async def test_get_events_between_applies_limit_and_order(monkeypatch):
    now = datetime.now()
    events = [
        CalendarEvent(
            title="Event A",
            start_date=now,
            end_date=now + timedelta(hours=1),
            calendar_name="Work",
            is_all_day=False,
        ),
        CalendarEvent(
            title="Event B",
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=1, hours=1),
            calendar_name="Work",
            is_all_day=False,
        ),
    ]
    result = CalendarEventsResult(
        events=events,
        reminders=[],
        query_start_date=now.date(),
        query_end_date=(now + timedelta(days=1)).date(),
        total_count=len(events),
        reminder_count=0,
        calendars_queried=["Work"],
    )

    backend = DummyBackend(result)
    monkeypatch.setattr(CalendarService, "_create_backend", lambda self: backend)

    service = CalendarService(CalendarConfig())
    limited = await service.get_events_between(now.date(), (now + timedelta(days=1)).date(), limit=1)

    assert len(limited.events) == 1
    assert limited.events[0].title == "Event A"
    assert limited.total_count == 1
    assert backend.queries[0].start_date == now.date()
    assert backend.queries[0].end_date == (now + timedelta(days=1)).date()


@pytest.mark.asyncio
async def test_get_events_between_validates_range(monkeypatch):
    result = CalendarEventsResult(
        events=[],
        reminders=[],
        query_start_date=None,
        query_end_date=None,
        total_count=0,
        reminder_count=0,
        calendars_queried=[],
    )
    backend = DummyBackend(result)
    monkeypatch.setattr(CalendarService, "_create_backend", lambda self: backend)

    service = CalendarService(CalendarConfig())

    with pytest.raises(ValueError):
        await service.get_events_between((datetime.now() + timedelta(days=1)).date(), datetime.now().date())
