from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from telegram_bot.service.life_context.fetcher import LifeContextFetcher
from telegram_bot.service.life_context.formatter import LifeContextFormatter
from telegram_bot.service.life_context.models import LifeContextConfig, LifeContextFormattedResponse, LifeContextRequest

if TYPE_CHECKING:
    from telegram_bot.service.calendar_service.calendar_service import CalendarService
    from telegram_bot.service.db_service import DBService
    from telegram_bot.service.life_context.garmin import GarminContextService
    from telegram_bot.service.obsidian.obsidian_service import ObsidianService


class LifeContextService:
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
        self._fetcher = LifeContextFetcher(
            config=config,
            tz=tz,
            obsidian_service=obsidian_service,
            garmin_service=garmin_service,
            calendar_service=calendar_service,
            db_service=db_service,
        )
        self._formatter = LifeContextFormatter(config=config, tz=tz)

    async def build_context(self, request: LifeContextRequest) -> LifeContextFormattedResponse:
        bundle = await self._fetcher.fetch(request)
        return self._formatter.format(bundle, request)
