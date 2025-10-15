from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    """Represents a single calendar event."""

    title: str = Field(description="Event title/summary")
    start_date: datetime = Field(description="Event start date and time")
    end_date: datetime = Field(description="Event end date and time")
    calendar_name: str = Field(description="Name of the calendar this event belongs to")
    location: Optional[str] = Field(default=None, description="Event location")
    notes: Optional[str] = Field(default=None, description="Event description/notes")
    is_all_day: bool = Field(default=False, description="Whether this is an all-day event")


class CalendarEventQuery(BaseModel):
    """Query parameters for fetching calendar events."""

    start_date: Optional[date] = Field(default=None, description="Start date for event query (inclusive)")
    end_date: Optional[date] = Field(default=None, description="End date for event query (inclusive)")
    calendar_names: Optional[list[str]] = Field(
        default=None, description="List of calendar names to include (None = all calendars)"
    )
    include_all_day: bool = Field(default=True, description="Whether to include all-day events")
    include_reminders: bool = Field(default=False, description="Whether to include reminders")


class CalendarReminder(BaseModel):
    """Represents a calendar reminder/notification."""

    title: str = Field(description="Reminder title")
    due_date: Optional[datetime] = Field(default=None, description="Due date and time")
    completed: bool = Field(default=False, description="Whether reminder is completed")
    priority: Optional[int] = Field(default=None, description="Priority level")
    notes: Optional[str] = Field(default=None, description="Reminder notes")
    list_name: str = Field(description="Name of the reminder list")


class CalendarEventsResult(BaseModel):
    """Result container for calendar events with metadata."""

    events: list[CalendarEvent] = Field(description="List of calendar events")
    reminders: list[CalendarReminder] = Field(default_factory=list, description="List of reminders")
    query_start_date: Optional[date] = Field(description="Actual start date used in query")
    query_end_date: Optional[date] = Field(description="Actual end date used in query")
    total_count: int = Field(description="Total number of events returned")
    reminder_count: int = Field(default=0, description="Total number of reminders returned")
    calendars_queried: list[str] = Field(description="List of calendar names that were queried")


# Pydantic models for parsing ekexport JSON output
class EkExportRecurrenceRule(BaseModel):
    """Recurrence rule from ekexport."""

    frequency: str
    interval: int


class EkExportEvent(BaseModel):
    """Event data from ekexport JSON output."""

    calendarId: str
    endDate: str
    id: str
    isAllDay: bool
    startDate: str
    timeZone: Optional[str] = None
    title: str
    location: Optional[str] = None
    notes: Optional[str] = None
    recurrenceRules: list[EkExportRecurrenceRule] = Field(default_factory=list)


class EkExportReminder(BaseModel):
    """Reminder data from ekexport JSON output."""

    id: str
    title: str
    completed: Optional[bool] = None
    priority: Optional[int] = None
    notes: Optional[str] = None
    dueDate: Optional[str] = None
    listName: Optional[str] = Field(default=None, alias="list")


class EkExportInfo(BaseModel):
    """Export metadata from ekexport."""

    eventCount: int
    reminderCount: int
    exportedBy: str
    timestamp: str


class EkExportCalendar(BaseModel):
    """Calendar metadata from ekexport list-calendars."""

    id: str
    title: str
    account: str
    type: str
    allowsModifications: bool
    colorHex: str


class EkExportListInfo(BaseModel):
    """List metadata from ekexport list-calendars."""

    calendarCount: int
    listedBy: str
    timestamp: str


class EkExportOutput(BaseModel):
    """Complete ekexport JSON output."""

    events: list[EkExportEvent] = Field(default_factory=list)
    reminders: list[EkExportReminder] = Field(default_factory=list)
    exportInfo: EkExportInfo


class EkExportCalendarList(BaseModel):
    """ekexport calendar list output."""

    calendars: list[EkExportCalendar]
    listInfo: EkExportListInfo
