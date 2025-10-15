from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Callable, Protocol
from zoneinfo import ZoneInfo

from loguru import logger

from telegram_bot.service.context_trigger.models import ContextTriggerConfig
from telegram_bot.service.life_context.models import LifeContextFormattedResponse, LifeContextMetric, LifeContextRequest

if TYPE_CHECKING:
    pass


class LifeContextServiceProtocol(Protocol):
    """Protocol defining the interface for life context services."""

    async def build_context(self, request: LifeContextRequest) -> LifeContextFormattedResponse:
        ...


class ContextAggregator:
    """Aggregates life context pieces for smart triggers via LifeContextService."""

    def __init__(
        self,
        *,
        life_context_service: LifeContextServiceProtocol,
        tz: ZoneInfo,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._life_context_service = life_context_service
        self._tz = tz
        self._now_provider = now_provider or (lambda: datetime.now(tz=self._tz))

    async def gather_context(self, config: ContextTriggerConfig) -> str:
        """Fetch requested metrics and assemble markdown for trigger analysis."""

        today = self._current_date()
        start_date = self._calculate_start_date(today, config)
        end_date = self._calculate_end_date(today, config)

        metrics = {
            LifeContextMetric.NOTES,
            LifeContextMetric.GARMIN,
            LifeContextMetric.CALENDAR,
            LifeContextMetric.CORRELATIONS,
            LifeContextMetric.VARIANCE,
        }

        request = LifeContextRequest(
            start_date=start_date,
            end_date=end_date,
            metrics=frozenset(metrics),
        )

        logger.debug(
            "Gathering smart-trigger context via LifeContextService: start=%s end=%s metrics=%s",
            start_date,
            end_date,
            sorted(metric.value for metric in metrics),
        )

        response = await self._life_context_service.build_context(request)

        if response.error:
            logger.warning(
                "LifeContextService returned error for smart trigger: %s",
                response.error,
            )
            return f"CONTEXT FETCH ERROR: {response.error}"

        parts = []

        notes_markdown = self._build_notes_markdown(response.sections.get(LifeContextMetric.NOTES.value), config)
        if notes_markdown:
            parts.append(f"RECENT DAILY NOTES:\n{notes_markdown}")

        garmin_markdown = self._section_markdown(response, LifeContextMetric.GARMIN)
        if garmin_markdown:
            parts.insert(0, f"GARMIN HEALTH DATA:\n{garmin_markdown}")

        calendar_markdown = self._section_markdown(response, LifeContextMetric.CALENDAR)
        if calendar_markdown:
            parts.append(f"CALENDAR EVENTS:\n{calendar_markdown}")

        correlation_markdown = self._section_markdown(response, LifeContextMetric.CORRELATIONS)
        if correlation_markdown:
            parts.append(f"CORRELATION HIGHLIGHTS:\n{correlation_markdown}")

        variance_markdown = self._section_markdown(response, LifeContextMetric.VARIANCE)
        if variance_markdown:
            parts.append(f"VARIANCE HIGHLIGHTS:\n{variance_markdown}")

        if not parts:
            return "NO CONTEXT DATA AVAILABLE"

        return "\n\n".join(parts)

    def _current_date(self) -> date:
        return self._now_provider().astimezone(self._tz).date()

    def _calculate_start_date(self, today: date, config: ContextTriggerConfig) -> date:
        """Calculate the start date for context fetching using the maximum lookback window.

        Note: obsidian_lookback_days and garmin_lookback_days represent "number of days
        to include" (e.g., 3 means today + 2 previous days, so lookback = 3-1 = 2 days back).
        By contrast, calendar_lookback_days and correlation lookback_days represent
        "days to go back from today" (e.g., 3 means go back 3 days).

        This inconsistency exists for historical reasons and ensures consistent behavior
        with the original implementation.
        """
        lookbacks = [
            max(config.obsidian_lookback_days - 1, 0),
            max(config.garmin_lookback_days - 1, 0),
            max(config.calendar_lookback_days, 0),
            max(config.correlation_fetch.lookback_days, 0),
        ]
        max_lookback = max(lookbacks) if lookbacks else 0
        return today - timedelta(days=max_lookback)

    def _calculate_end_date(self, today: date, config: ContextTriggerConfig) -> date:
        lookahead = max(config.calendar_lookahead_days, 0)
        return today + timedelta(days=lookahead)

    def _section_markdown(self, response: LifeContextFormattedResponse, metric: LifeContextMetric) -> str | None:
        section = response.sections.get(metric.value)
        if not section:
            return None
        markdown = section.get("markdown")
        if markdown:
            return markdown.strip()
        data = section.get("data")
        if data is None:
            return None
        return str(data).strip() or None

    def _build_notes_markdown(self, section: dict | None, config: ContextTriggerConfig) -> str | None:
        """Build markdown for notes section.

        Note: Applies obsidian_lookback_days limit here as a secondary filter.
        The LifeContextService fetches notes based on date range and its internal
        notes_limit config, but we apply an additional limit here to respect the
        smart trigger's specific obsidian_lookback_days setting.
        """
        if not section:
            return None

        items = section.get("data", {}).get("items") or []
        limit = max(config.obsidian_lookback_days, 0)
        if limit:
            items = items[:limit]

        markdown_lines: list[str] = []
        for item in items:
            date_str = item.get("date")
            content = (item.get("content") or "").strip()
            if not date_str:
                continue
            display = content if content else "_(empty note)_"
            markdown_lines.append(f"**{date_str}**\n{display}")

        if markdown_lines:
            return "\n\n".join(markdown_lines)

        markdown = section.get("markdown")
        return markdown.strip() if markdown else None
