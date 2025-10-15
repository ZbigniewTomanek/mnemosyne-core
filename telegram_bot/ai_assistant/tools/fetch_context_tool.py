"""AI assistant tool for fetching user life context (notes, Garmin, calendar, correlations, variance)."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents import FunctionTool
from zoneinfo import ZoneInfo

from agents import function_tool

from telegram_bot.service.life_context.models import LifeContextMetric, LifeContextRequest
from telegram_bot.service.life_context.service import LifeContextService


def create_fetch_context_tool(life_context_service: LifeContextService, tz: ZoneInfo) -> FunctionTool:
    """Factory function to create a fetch_context tool with the life context service injected.

    Args:
        life_context_service: The LifeContextService instance to use for fetching data
        tz: Timezone for date operations

    Returns:
        A function_tool decorated async function that can be used by the AI assistant
    """

    @function_tool
    async def fetch_context(
        start_date: str | None = None,
        end_date: str | None = None,
        metrics: str | list[str] = "all",
    ) -> dict[str, Any]:
        """
        Fetch comprehensive life context data for a date range, including daily notes,
        Garmin health metrics, calendar events, correlation insights, and variance alerts.

        This tool allows you to retrieve rich historical context about the user's life
        to answer questions like "How was my health last week?" or "What did I do yesterday?".

        **Available Metrics:**
        - "notes" - Daily notes from Obsidian
        - "persistent_memory" - Persistent memory content
        - "garmin" - Garmin health data (sleep, steps, heart rate, stress, body battery)
        - "calendar" - Calendar events and reminders
        - "correlations" - Activity correlation insights
        - "variance" - Notable variance alerts for activities
        - "all" - Fetch all available metrics (default)

        **Usage Examples:**

        Get all context for the last 7 days:
        ```python
        fetch_context()
        ```

        Get Garmin and notes for a specific week:
        ```python
        fetch_context(start_date="2025-01-01", end_date="2025-01-07", metrics=["garmin", "notes"])
        ```

        Get just variance and correlations for last month:
        ```python
        fetch_context(start_date="2024-12-01", metrics=["variance", "correlations"])
        ```

        **Response Format:**
        Returns a dictionary with:
        - "sections": Dict of metric sections with structured data and markdown
        - "rendered_markdown": Complete formatted markdown summary (or None if token budget exceeded)
        - "error": Error message if any (e.g., token budget exceeded)
        - "date_range": The actual date range fetched

        Args:
            start_date: Start date in YYYY-MM-DD format. Defaults to (end_date - 7 days).
            end_date: End date in YYYY-MM-DD format. Defaults to today.
            metrics: Either "all" or a list of metric names to fetch.
                    Valid values: "notes", "persistent_memory", "garmin", "calendar",
                    "correlations", "variance"

        Returns:
            Dictionary containing structured context data and formatted markdown summary.

        Raises:
            ValueError: If date format is invalid or dates are in wrong order.
        """
        # Parse dates
        parsed_start: date | None = None
        parsed_end: date | None = None

        if start_date is not None:
            try:
                parsed_start = datetime.fromisoformat(start_date).date()
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid start_date format. Expected YYYY-MM-DD, got: {start_date}") from exc

        if end_date is not None:
            try:
                parsed_end = datetime.fromisoformat(end_date).date()
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid end_date format. Expected YYYY-MM-DD, got: {end_date}") from exc

        # Parse metrics
        requested_metrics: set[LifeContextMetric]
        if metrics == "all":
            requested_metrics = set(LifeContextMetric)
        elif isinstance(metrics, str):
            # Single metric provided as string
            try:
                requested_metrics = {LifeContextMetric(metrics)}
            except ValueError as exc:
                valid_values = [m.value for m in LifeContextMetric]
                raise ValueError(f"Invalid metric '{metrics}'. Valid values: {', '.join(valid_values)}") from exc
        elif isinstance(metrics, list):
            # List of metrics provided
            requested_metrics = set()
            for metric_str in metrics:
                try:
                    requested_metrics.add(LifeContextMetric(metric_str))
                except ValueError as exc:
                    valid_values = [m.value for m in LifeContextMetric]
                    raise ValueError(f"Invalid metric '{metric_str}'. Valid values: {', '.join(valid_values)}") from exc
        else:
            raise ValueError(f"metrics must be 'all', a string, or a list of strings. Got: {type(metrics)}")

        # Build request
        request = LifeContextRequest(
            start_date=parsed_start,
            end_date=parsed_end,
            metrics=frozenset(requested_metrics),
        )

        # Fetch context
        response = await life_context_service.build_context(request)

        # Build response dict
        result: dict[str, Any] = {
            "sections": response.sections,
            "rendered_markdown": response.rendered_markdown,
            "error": response.error,
            "date_range": {
                "start_date": response.bundle.start_date.isoformat(),
                "end_date": response.bundle.end_date.isoformat(),
            },
        }

        return result

    return fetch_context
