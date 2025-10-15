from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from telegram_bot.service.calendar_service.exceptions import CalendarBackendError
from telegram_bot.service.calendar_service.models import (
    CalendarEvent,
    CalendarEventQuery,
    CalendarEventsResult,
    CalendarReminder,
    EkExportCalendarList,
    EkExportOutput,
)


class CalendarConfig(BaseModel):
    """Configuration for the calendar service."""

    backend: str = Field(default="ekexport", description="Calendar backend to use (ekexport or applescript)")
    default_lookback_days: int = Field(default=0, description="Default number of days to look back")
    default_lookahead_days: int = Field(default=1, description="Default number of days to look ahead")
    timezone: str = Field(default="Europe/Warsaw", description="Timezone for calendar operations")
    excluded_title_patterns: list[str] = Field(
        default_factory=list, description="Regex patterns for event titles to exclude from results"
    )

    @cached_property
    def tz(self) -> ZoneInfo:
        """Get timezone object."""
        try:
            return ZoneInfo(self.timezone)
        except Exception as e:
            raise ValueError(f"Invalid timezone specified: {self.timezone}") from e

    @cached_property
    def excluded_title_compiled_patterns(self) -> list[re.Pattern]:
        """Compile excluded title regex patterns."""
        return [re.compile(pat, re.IGNORECASE) for pat in self.excluded_title_patterns if pat]


class CalendarBackend(ABC):
    """Abstract base class for calendar backends."""

    @abstractmethod
    async def get_events(self, query: CalendarEventQuery, config: CalendarConfig) -> CalendarEventsResult:
        """Fetch calendar events based on query parameters."""


class EkExportCalendarBackend(CalendarBackend):
    """ekexport-based calendar backend for macOS Calendar app."""

    def __init__(self) -> None:
        self._binary_path = Path(__file__).parent / "bin" / "ekexport"
        if not self._binary_path.exists():
            raise FileNotFoundError(f"ekexport binary not found: {self._binary_path}")
        self._calendar_cache: dict[str, str] = {}  # id -> name mapping

    async def get_events(self, query: CalendarEventQuery, config: CalendarConfig) -> CalendarEventsResult:
        """Fetch events using ekexport with async subprocess calls."""
        start_date, end_date = self._build_date_range(query, config)

        # Get calendar metadata if needed for filtering
        if query.calendar_names is not None:
            await self._ensure_calendar_cache()

        # Build ekexport command args
        args = self._build_export_args(start_date, end_date, query)

        # Execute ekexport asynchronously
        stdout_text = await self._run_ekexport(args, timeout_s=30)
        events, reminders, calendars_queried = await self._parse_output(stdout_text, config, query)

        # Sort events by start time
        events.sort(key=lambda x: x.start_date)

        return CalendarEventsResult(
            events=events,
            reminders=reminders,
            query_start_date=start_date,
            query_end_date=end_date,
            total_count=len(events),
            reminder_count=len(reminders),
            calendars_queried=sorted(calendars_queried),
        )

    @staticmethod
    def _build_date_range(query: CalendarEventQuery, config: CalendarConfig) -> tuple[date, date]:
        tz = ZoneInfo(config.timezone)
        today = datetime.now(tz=tz).date()
        start_date = query.start_date or (today - timedelta(days=config.default_lookback_days))
        end_date = query.end_date or (today + timedelta(days=config.default_lookahead_days + 1))
        return start_date, end_date

    def _build_export_args(self, start_date: date, end_date: date, query: CalendarEventQuery) -> list[str]:
        """Build command line arguments for ekexport."""
        args = [
            "export",
            "--start-date",
            start_date.strftime("%Y-%m-%d"),
            "--end-date",
            end_date.strftime("%Y-%m-%d"),
            "--format",
            "json",
        ]

        # Add reminders if requested
        if query.include_reminders:
            args.append("--include-reminders")

        # Add calendar filtering if specified
        if query.calendar_names is not None:
            calendar_ids = []
            for name in query.calendar_names:
                # Find calendar ID by name
                calendar_id = next((cid for cid, cname in self._calendar_cache.items() if cname == name), None)
                if calendar_id:
                    calendar_ids.append(calendar_id)

            if calendar_ids:
                args.extend(["--calendars", ",".join(calendar_ids)])

        return args

    async def _ensure_calendar_cache(self) -> None:
        """Ensure calendar ID to name mapping is cached."""
        if not self._calendar_cache:
            await self._refresh_calendar_cache()

    async def _refresh_calendar_cache(self) -> None:
        """Refresh the calendar ID to name mapping cache."""
        args = ["list-calendars", "--format", "json"]
        stdout_text = await self._run_ekexport(args, timeout_s=10)

        try:
            calendar_list = EkExportCalendarList.model_validate_json(stdout_text)
            self._calendar_cache = {cal.id: cal.title for cal in calendar_list.calendars}
            logger.debug(f"Cached {len(self._calendar_cache)} calendar mappings")
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Failed to parse calendar list: {e}")
            raise CalendarBackendError(f"Failed to parse calendar list: {e}") from e

    async def _run_ekexport(self, args: list[str], timeout_s: int = 30) -> str:
        """Execute ekexport binary asynchronously (non-blocking)."""
        cmd = [self._binary_path.as_posix(), *args]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError as e:
            proc.kill()
            try:
                await proc.communicate()
            except Exception:
                pass
            raise CalendarBackendError("ekexport execution timed out") from e

        if proc.returncode != 0:
            err_text = stderr.decode(errors="ignore") if stderr else ""
            raise CalendarBackendError.from_process_error(proc.returncode, err_text)

        stdout_text = stdout.decode(errors="ignore") if stdout else "{}"
        logger.debug(f"ekexport output: {stdout_text[:500]}...")
        return stdout_text

    async def _parse_output(
        self, stdout_text: str, config: CalendarConfig, query: CalendarEventQuery
    ) -> tuple[list[CalendarEvent], list[CalendarReminder], list[str]]:
        """Parse ekexport JSON output using Pydantic models."""
        try:
            export_data = EkExportOutput.model_validate_json(stdout_text)
        except (json.JSONDecodeError, ValidationError) as e:
            raise CalendarBackendError.from_parse_error(stdout_text, reason=str(e)) from e

        events: list[CalendarEvent] = []
        reminders: list[CalendarReminder] = []
        calendars_queried: set[str] = set()

        # Ensure calendar cache is available for name resolution
        if not self._calendar_cache:
            await self._refresh_calendar_cache()

        # Process events
        for event_data in export_data.events:
            try:
                # Resolve calendar name from ID
                calendar_name = self._calendar_cache.get(event_data.calendarId, f"Unknown ({event_data.calendarId})")
                calendars_queried.add(calendar_name)

                # Apply query filters
                if query.calendar_names is not None and calendar_name not in set(query.calendar_names):
                    continue
                if not query.include_all_day and event_data.isAllDay:
                    continue

                if any(pattern.search(event_data.title) for pattern in config.excluded_title_compiled_patterns):
                    logger.debug(f"Excluding event '{event_data.title}' due to exclusion pattern")
                    continue
                # Parse datetime strings - ekexport returns ISO format with Z suffix
                start_dt = datetime.fromisoformat(event_data.startDate.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(event_data.endDate.replace("Z", "+00:00"))

                # Convert to configured timezone
                start_dt = start_dt.astimezone(config.tz)
                end_dt = end_dt.astimezone(config.tz)

                event = CalendarEvent(
                    title=event_data.title,
                    start_date=start_dt,
                    end_date=end_dt,
                    calendar_name=calendar_name,
                    location=event_data.location,
                    notes=event_data.notes,
                    is_all_day=event_data.isAllDay,
                )
                events.append(event)

            except (ValueError, TypeError, ValidationError) as e:
                logger.debug(f"Skipping invalid event: {e}; event={event_data}")
                continue

        # Process reminders if included
        if query.include_reminders:
            for reminder_data in export_data.reminders:
                try:
                    due_date = None
                    if reminder_data.dueDate:
                        due_date = datetime.fromisoformat(reminder_data.dueDate.replace("Z", "+00:00")).astimezone(
                            config.tz
                        )

                    reminder = CalendarReminder(
                        title=reminder_data.title,
                        due_date=due_date,
                        completed=reminder_data.completed or False,
                        priority=reminder_data.priority,
                        notes=reminder_data.notes,
                        list_name=reminder_data.listName or "Unknown List",
                    )
                    reminders.append(reminder)

                except (ValueError, TypeError, ValidationError) as e:
                    logger.debug(f"Skipping invalid reminder: {e}; reminder={reminder_data}")
                    continue

        return events, reminders, list(calendars_queried)


class CalendarService:
    """Generic calendar service with pluggable backends."""

    def __init__(self, config: CalendarConfig):
        self.config = config
        self._backend = self._create_backend()

        logger.info(f"Initialized CalendarService with {config.backend} backend")

    def _create_backend(self) -> CalendarBackend:
        """Create the appropriate calendar backend based on configuration."""
        if self.config.backend == "ekexport":
            return EkExportCalendarBackend()
        else:
            raise ValueError(f"Unsupported calendar backend: {self.config.backend}")

    async def get_events(self, query: Optional[CalendarEventQuery] = None) -> CalendarEventsResult:
        """Fetch calendar events using the configured backend."""
        if query is None:
            query = CalendarEventQuery()

        logger.debug(f"Fetching calendar events: {query}")
        result = await self._backend.get_events(query, self.config)
        logger.info(f"Retrieved {result.total_count} calendar events")

        return result

    async def get_events_between(
        self,
        start_date: date,
        end_date: date,
        *,
        limit: int | None = None,
        include_all_day: bool = True,
        include_reminders: bool = True,
    ) -> CalendarEventsResult:
        """Fetch events between explicit dates with optional limiting."""

        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

        query = CalendarEventQuery(
            start_date=start_date,
            end_date=end_date,
            include_all_day=include_all_day,
            include_reminders=include_reminders,
        )

        result = await self.get_events(query)

        if limit is None or limit < 0:
            return result

        trimmed_events = result.events[: limit or 0]
        return result.model_copy(update={"events": trimmed_events, "total_count": len(trimmed_events)})

    def format_events_for_context(self, result: CalendarEventsResult) -> Optional[str]:
        """Format calendar events and reminders for LLM context.

        Returns a combined string with sections for events and, if present,
        reminders. Returns None only when both events and reminders are empty.
        """
        if not result.events and not result.reminders:
            return None

        context_parts: list[str] = []

        # Group events by date
        events_by_date = {}
        for event in result.events:
            event_date = event.start_date.date()
            if event_date not in events_by_date:
                events_by_date[event_date] = []
            events_by_date[event_date].append(event)

        # Format each day's events
        for event_date in sorted(events_by_date.keys()):
            day_events = events_by_date[event_date]

            # Format date header
            if event_date == datetime.now(ZoneInfo(self.config.timezone)).date():
                date_header = "Today"
            elif event_date == datetime.now(ZoneInfo(self.config.timezone)).date() + timedelta(days=1):
                date_header = "Tomorrow"
            else:
                date_header = event_date.strftime("%A, %B %d")

            context_parts.append(f"{date_header}:")

            # Format events for this day
            for event in day_events:
                if event.is_all_day:
                    time_str = "All-Day"
                else:
                    time_str = f"{event.start_date.strftime('%H:%M')}-{event.end_date.strftime('%H:%M')}"

                event_line = f"  • {time_str}: {event.title}"

                if event.location:
                    event_line += f" @ {event.location}"

                if event.calendar_name and len(events_by_date) > 1:  # Show calendar name if multiple days
                    event_line += f" [{event.calendar_name}]"

                context_parts.append(event_line)

        # Append reminders section if available
        if result.reminders:
            context_parts.append("")
            context_parts.append("Reminders:")
            # Group by list name, then by due time
            reminders_by_list: dict[str, list[CalendarReminder]] = {}
            for r in result.reminders:
                reminders_by_list.setdefault(r.list_name, []).append(r)

            for list_name in sorted(reminders_by_list.keys()):
                context_parts.append(f"  [{list_name}]")
                # Sort: incomplete first, then by due date
                sorted_list = sorted(
                    reminders_by_list[list_name],
                    key=lambda x: (
                        x.completed,  # False comes first, True comes last
                        x.due_date or datetime.max.replace(tzinfo=ZoneInfo(self.config.timezone)),
                    ),
                )
                for r in sorted_list:
                    status = "✓" if r.completed is True else "•"
                    if r.due_date:
                        due_str = r.due_date.strftime("%Y-%m-%d %H:%M")
                    else:
                        due_str = "(brak terminu)"
                    notes_suffix = f" — {r.notes}" if r.notes else ""
                    context_parts.append(f"    {status} {r.title} — {due_str}{notes_suffix}")

        return "\n".join(context_parts)

    async def get_today_events(self, include_reminders: bool = True) -> CalendarEventsResult:
        """Convenience method to get today's events."""
        today = datetime.now(ZoneInfo(self.config.timezone)).date()
        query = CalendarEventQuery(
            start_date=today, end_date=today + timedelta(days=1), include_reminders=include_reminders
        )
        return await self.get_events(query)

    async def get_upcoming_events(self, days: int = 3) -> CalendarEventsResult:
        """Convenience method to get upcoming events for the next N days."""
        today = datetime.now(ZoneInfo(self.config.timezone)).date()
        end_date = today + timedelta(days=days + 1)
        query = CalendarEventQuery(start_date=today, end_date=end_date)
        return await self.get_events(query)
