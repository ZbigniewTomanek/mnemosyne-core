from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from telegram_bot.service.life_context.models import (
    LifeContextBundle,
    LifeContextConfig,
    LifeContextMetric,
    LifeContextRequest,
)

if TYPE_CHECKING:
    from telegram_bot.service.calendar_service.calendar_service import CalendarService
    from telegram_bot.service.db_service import DBService
    from telegram_bot.service.life_context.garmin import GarminContextService
    from telegram_bot.service.obsidian.obsidian_service import ObsidianService


class LifeContextFetcher:
    """Fetch raw life-context data from domain services, scoped to requested metrics."""

    def __init__(
        self,
        *,
        config: LifeContextConfig,
        tz: ZoneInfo,
        obsidian_service: ObsidianService | None,
        garmin_service: GarminContextService | None,
        calendar_service: CalendarService | None,
        db_service: DBService | None,
    ) -> None:
        self._config = config
        self._tz = tz
        self._obsidian = obsidian_service
        self._garmin = garmin_service
        self._calendar = calendar_service
        self._db = db_service

    async def fetch(self, request: LifeContextRequest) -> LifeContextBundle:
        end_date = request.end_date or datetime.now(tz=self._tz).date()
        start_date = request.start_date or self._default_start_date(end_date)
        metrics = request.metrics

        notes_by_date = None
        persistent_memory = None
        garmin_payload = None
        calendar_payload = None
        correlation_payload = None
        variance_payload = None

        if LifeContextMetric.NOTES in metrics and self._obsidian is not None:
            notes_by_date = await self._obsidian.get_daily_notes_between(
                start_date=start_date,
                end_date=end_date,
                max_notes=self._config.notes_limit,
            )

        if LifeContextMetric.PERSISTENT_MEMORY in metrics and self._obsidian is not None:
            persistent_memory = await self._obsidian.get_persistent_memory_content()

        if LifeContextMetric.GARMIN in metrics and self._garmin is not None:
            garmin_payload = await self._garmin.get_window(start_date=start_date, end_date=end_date)

        if LifeContextMetric.CALENDAR in metrics and self._calendar is not None:
            calendar_payload = await self._calendar.get_events_between(
                start_date=start_date,
                end_date=end_date,
                limit=self._config.calendar_limit,
            )

        if LifeContextMetric.CORRELATIONS in metrics and self._db is not None:
            lookback_days = (datetime.now(tz=self._tz).date() - start_date).days
            correlation_payload = await asyncio.to_thread(
                self._db.fetch_correlation_events,
                lookback_days=lookback_days,
                limit=self._config.correlation_limit,
            )

        if LifeContextMetric.VARIANCE in metrics and self._db is not None:
            variance_payload = await asyncio.to_thread(
                self._db.fetch_activity_variances,
                start_date=start_date,
                end_date=end_date,
                limit=self._config.variance_limit,
                min_score=self._config.variance_min_score,
            )

        return LifeContextBundle(
            start_date=start_date,
            end_date=end_date,
            notes_by_date=notes_by_date,
            garmin=garmin_payload,
            calendar=calendar_payload,
            correlations=correlation_payload,
            variance=variance_payload,
            persistent_memory=persistent_memory,
        )

    def _default_start_date(self, end_date: date) -> date:
        lookback = max(self._config.default_lookback_days - 1, 0)
        return end_date - timedelta(days=lookback)
