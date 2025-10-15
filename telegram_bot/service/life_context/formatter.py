from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence, cast
from zoneinfo import ZoneInfo

import pandas as pd

from telegram_bot.service.context_trigger.garmin_formatter import (
    format_current_sleep_status_md,
    format_garmin_data_for_context,
    format_garmin_day_markdown_md,
)
from telegram_bot.service.correlation_engine.formatting import format_activity_variances, format_correlation_events
from telegram_bot.service.life_context.models import (
    LifeContextBundle,
    LifeContextConfig,
    LifeContextFormattedResponse,
    LifeContextMetric,
    LifeContextRequest,
)

_SECTION_TITLES: dict[LifeContextMetric, str] = {
    LifeContextMetric.NOTES: "Daily Notes",
    LifeContextMetric.GARMIN: "Garmin Metrics",
    LifeContextMetric.CALENDAR: "Calendar",
    LifeContextMetric.CORRELATIONS: "Correlation Events",
    LifeContextMetric.VARIANCE: "Variance Alerts",
    LifeContextMetric.PERSISTENT_MEMORY: "Persistent Memory",
}

_SECTION_ORDER: tuple[LifeContextMetric, ...] = (
    LifeContextMetric.NOTES,
    LifeContextMetric.GARMIN,
    LifeContextMetric.CALENDAR,
    LifeContextMetric.CORRELATIONS,
    LifeContextMetric.VARIANCE,
    LifeContextMetric.PERSISTENT_MEMORY,
)


class LifeContextFormatter:
    def __init__(self, *, config: LifeContextConfig, tz: ZoneInfo) -> None:
        self._config = config
        self._tz = tz

    def format(self, bundle: LifeContextBundle, request: LifeContextRequest) -> LifeContextFormattedResponse:
        sections: dict[str, dict[str, Any | None]] = {}
        markdown_parts: list[str] = []

        for metric in self._metrics_order_for_request(request):
            content = self._extract_metric_content(bundle, metric)
            if content is None:
                continue

            data, markdown = self._build_section(metric, content)
            markdown = self._normalise_markdown(markdown)

            if data is None and markdown is None:
                continue

            sections[metric.value] = {"data": data, "markdown": markdown}

            if markdown:
                title = _SECTION_TITLES[metric]
                markdown_parts.append(self._render_section(title, markdown))

        rendered_markdown = "\n\n".join(markdown_parts)
        token_budget = request.max_token_budget or self._config.max_token_budget
        estimated_tokens = estimate_tokens(rendered_markdown)

        if token_budget is not None and estimated_tokens > token_budget:
            error_message = f"Token budget exceeded: estimated {estimated_tokens} tokens but limit is {token_budget}."
            return LifeContextFormattedResponse(
                bundle=bundle,
                sections=sections,
                rendered_markdown=None,
                error=error_message,
            )

        return LifeContextFormattedResponse(
            bundle=bundle,
            sections=sections,
            rendered_markdown=rendered_markdown or None,
            error=None,
        )

    def _metrics_order_for_request(self, request: LifeContextRequest) -> Iterable[LifeContextMetric]:
        requested = request.metrics
        return [metric for metric in _SECTION_ORDER if metric in requested]

    @staticmethod
    def _extract_metric_content(bundle: LifeContextBundle, metric: LifeContextMetric) -> Any | None:
        if metric is LifeContextMetric.NOTES:
            return bundle.notes_by_date
        if metric is LifeContextMetric.GARMIN:
            return bundle.garmin
        if metric is LifeContextMetric.CALENDAR:
            return bundle.calendar
        if metric is LifeContextMetric.CORRELATIONS:
            return bundle.correlations
        if metric is LifeContextMetric.VARIANCE:
            return bundle.variance
        if metric is LifeContextMetric.PERSISTENT_MEMORY:
            return bundle.persistent_memory
        return None

    def _build_section(self, metric: LifeContextMetric, content: Any) -> tuple[Any | None, str | None]:
        if metric is LifeContextMetric.NOTES:
            return self._build_notes_section(content)
        if metric is LifeContextMetric.GARMIN:
            return self._build_garmin_section(content)
        if metric is LifeContextMetric.CALENDAR:
            return self._build_calendar_section(content)
        if metric is LifeContextMetric.CORRELATIONS:
            return self._build_correlation_section(content)
        if metric is LifeContextMetric.VARIANCE:
            return self._build_variance_section(content)
        if metric is LifeContextMetric.PERSISTENT_MEMORY:
            return self._build_persistent_memory_section(content)
        return self._fallback_section(content)

    def _build_notes_section(self, notes: dict[str, str] | None) -> tuple[Any | None, str | None]:
        if not notes:
            return None, None

        ordered_items: list[dict[str, Any]] = []
        lines: list[str] = []
        for date_str in sorted(notes.keys(), reverse=True):
            body = (notes[date_str] or "").strip()
            ordered_items.append({"date": date_str, "content": body})
            display = body if body else "_(empty note)_"
            lines.append(f"**{date_str}**\n{display}")

        return {"items": ordered_items}, "\n\n".join(lines)

    def _build_garmin_section(self, garmin: Any) -> tuple[Any | None, str | None]:
        if garmin is None:
            return None, None

        if hasattr(garmin, "sleep_summary"):
            summary_data, markdown_parts = self._summarise_garmin_data(garmin)
            markdown = "\n\n".join(part for part in markdown_parts if part)
            return summary_data, markdown or None

        # Pre-summarised objects (dicts) fall back to JSON + markdown coercion
        return self._to_jsonable(garmin), _coerce_to_markdown_block(garmin)

    def _build_calendar_section(self, result: Any) -> tuple[Any | None, str | None]:
        if result is None:
            return None, None

        data = self._to_jsonable(result)
        markdown = self._format_calendar_markdown(result)
        return data, markdown

    def _build_correlation_section(self, correlations: Sequence[Any] | None) -> tuple[Any | None, str | None]:
        if not correlations:
            return None, None

        markdown = format_correlation_events(
            correlations,
            tz=self._tz,
            max_events=self._config.correlation_limit,
        )
        return self._to_jsonable(correlations), markdown or None

    def _build_variance_section(self, variances: Sequence[Any] | None) -> tuple[Any | None, str | None]:
        if not variances:
            return None, None

        markdown = format_activity_variances(
            variances,
            tz=self._tz,
            max_items=self._config.variance_limit,
        )
        return self._to_jsonable(variances), markdown or None

    @staticmethod
    def _build_persistent_memory_section(memory: Any) -> tuple[Any | None, str | None]:
        if memory is None:
            return None, None
        text = str(memory).strip()
        if not text:
            return None, None
        return text, text

    def _fallback_section(self, content: Any) -> tuple[Any | None, str | None]:
        if content is None:
            return None, None
        return self._to_jsonable(content), _coerce_to_markdown_block(content)

    def _summarise_garmin_data(self, garmin: Any) -> tuple[dict[str, Any] | None, list[str]]:
        summary: dict[str, Any] = {}
        sections: list[str] = []

        bb_current = self._extract_body_battery_current(garmin)

        sleep_snapshot = self._extract_sleep_snapshot(garmin, bb_current)
        if sleep_snapshot:
            summary["sleep"] = sleep_snapshot
            try:
                sections.append(format_current_sleep_status_md(sleep_snapshot, self._tz))
            except Exception:
                pass

        if bb_current is not None:
            summary.setdefault("body_battery", {})["current"] = bb_current

        try:
            overview_md = format_garmin_data_for_context(garmin, self._tz)
        except Exception:
            overview_md = None
        if overview_md:
            summary["overview"] = overview_md
            sections.append(overview_md)

        daily_summary, daily_markdown = self._extract_daily_stats_markdown(garmin)
        if daily_summary:
            summary["daily_stats"] = daily_summary
        sections.extend(daily_markdown)

        return (summary or None, sections)

    def _extract_sleep_snapshot(self, garmin: Any, bb_current: int | None) -> dict[str, Any] | None:
        sleep_summary = getattr(garmin, "sleep_summary", None)
        if sleep_summary is None or getattr(sleep_summary, "empty", True):
            return None
        try:
            last_row = sleep_summary.iloc[-1]
        except Exception:
            return None

        snapshot = {
            "sleep_score": self._safe_int(last_row.get("sleepScore")),
            "sleep_time_s": self._safe_int(last_row.get("sleepTimeSeconds")),
            "deep_s": self._safe_int(last_row.get("deepSleepSeconds")),
            "light_s": self._safe_int(last_row.get("lightSleepSeconds")),
            "rem_s": self._safe_int(last_row.get("remSleepSeconds")),
            "restless_cnt": self._safe_int(last_row.get("restlessMomentsCount")),
            "avg_overnight_hrv": self._safe_float(last_row.get("avgOvernightHrv"), default=None),
            "bb_delta_sleep": self._safe_int(last_row.get("bodyBatteryChange")),
        }
        if bb_current is not None:
            snapshot["bb_current"] = bb_current
        return self._drop_none(snapshot)

    def _extract_body_battery_current(self, garmin: Any) -> int | None:
        bb_df = getattr(garmin, "body_battery_intraday", None)
        if bb_df is None or getattr(bb_df, "empty", True):
            return None
        try:
            last_row = bb_df.iloc[-1]
            value = last_row.get("BodyBatteryLevel")
            return self._safe_int(value, default=None)
        except Exception:
            return None

    def _extract_daily_stats_markdown(self, garmin: Any) -> tuple[list[dict[str, Any]], list[str]]:
        daily_df = getattr(garmin, "daily_stats", None)
        if daily_df is None or getattr(daily_df, "empty", True):
            return [], []

        try:
            tail_count = min(len(daily_df), 3)
            df = daily_df.tail(tail_count).copy()
        except Exception:
            return [], []

        if "calendarDate" in df.columns:
            df["__date"] = pd.to_datetime(df["calendarDate"], errors="coerce").dt.date
        elif "date" in df.columns:
            df["__date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        else:
            df["__date"] = pd.NaT
        df = df.dropna(subset=["__date"])
        df = df.iloc[::-1]  # Newest first

        summaries: list[dict[str, Any]] = []
        markdown_parts: list[str] = []

        for _, row in df.iterrows():
            day_date = row["__date"]
            if isinstance(day_date, pd.Timestamp):
                day_date = day_date.date()
            if not isinstance(day_date, date):
                continue

            steps = self._safe_int(row.get("totalSteps")) or 0
            active_kcal = self._safe_int(row.get("activeKilocalories")) or 0
            resting_hr = self._safe_int(row.get("restingHeartRate")) or 0
            hr_min = self._safe_int(row.get("minHeartRate"), default=None)
            if hr_min is None:
                hr_min = self._safe_int(row.get("minAvgHeartRate")) or 0
            hr_max = self._safe_int(row.get("maxHeartRate"), default=None)
            if hr_max is None:
                hr_max = self._safe_int(row.get("maxAvgHeartRate")) or 0
            hr_avg = self._safe_int(row.get("averageHeartRate"), default=None)
            if hr_avg is None:
                hr_avg = self._safe_int(row.get("restingHeartRate")) or 0

            stress_snapshot = {
                "stress_pct": self._safe_float(row.get("stressPercentage"), default=None),
                "low_pct": self._safe_float(row.get("lowStressPercentage"), default=None),
                "medium_pct": self._safe_float(row.get("mediumStressPercentage"), default=None),
                "high_pct": self._safe_float(row.get("highStressPercentage"), default=None),
            }

            body_battery_snapshot = {
                "high": self._safe_int(row.get("bodyBatteryHighestValue"), default=None),
                "avg": self._safe_int(row.get("bodyBatteryAtWakeTime"), default=None),
                "low": self._safe_int(row.get("bodyBatteryLowestValue"), default=None),
            }

            summary_entry = {
                "date": day_date.isoformat(),
                "steps": steps,
                "active_kcal": active_kcal,
                "resting_hr": resting_hr,
                "hr_min": hr_min,
                "hr_avg": hr_avg,
                "hr_max": hr_max,
                "stress": self._drop_none(stress_snapshot),
                "body_battery": self._drop_none(body_battery_snapshot),
            }
            summaries.append(summary_entry)

            stress_for_md = {
                "stress_pct": stress_snapshot["stress_pct"] if stress_snapshot["stress_pct"] is not None else 0.0,
                "low_pct": stress_snapshot["low_pct"] if stress_snapshot["low_pct"] is not None else 0.0,
                "medium_pct": stress_snapshot["medium_pct"] if stress_snapshot["medium_pct"] is not None else 0.0,
                "high_pct": stress_snapshot["high_pct"] if stress_snapshot["high_pct"] is not None else 0.0,
            }
            body_battery_for_md = {
                "high": body_battery_snapshot["high"] if body_battery_snapshot["high"] is not None else 0,
                "avg": body_battery_snapshot["avg"] if body_battery_snapshot["avg"] is not None else 0,
                "low": body_battery_snapshot["low"] if body_battery_snapshot["low"] is not None else 0,
            }

            day_payload = {
                "date": day_date,
                "steps": steps,
                "active_kcal": active_kcal,
                "resting_hr": resting_hr,
                "hr_min": hr_min or 0,
                "hr_avg": hr_avg or 0,
                "hr_max": hr_max or 0,
                "stress": stress_for_md,
                "body_battery": body_battery_for_md,
                "activities": [],
            }
            try:
                day_md = format_garmin_day_markdown_md(day_payload, self._tz)
            except Exception:
                day_md = None
            if day_md:
                markdown_parts.append(self._promote_subheading(day_md))

        return summaries, markdown_parts

    def _format_calendar_markdown(self, result: Any) -> str | None:
        events = getattr(result, "events", None) or []
        reminders = getattr(result, "reminders", None) or []
        if not events and not reminders:
            return None

        lines: list[str] = []
        today = datetime.now(tz=self._tz).date()
        tomorrow = today + timedelta(days=1)

        events_by_date: dict[date, list[tuple[datetime, datetime, Any]]] = {}
        for event in events:
            start_local = self._ensure_timezone(event.start_date)
            end_local = self._ensure_timezone(event.end_date)
            event_date = start_local.date()
            events_by_date.setdefault(event_date, []).append((start_local, end_local, event))

        for event_date in sorted(events_by_date.keys()):
            if event_date == today:
                header = "Today"
            elif event_date == tomorrow:
                header = "Tomorrow"
            else:
                header = event_date.strftime("%A, %B %d")
            lines.append(f"**{header}**")

            day_events = sorted(events_by_date[event_date], key=lambda item: item[0])
            for start_local, end_local, event in day_events:
                time_str = (
                    "All-day" if event.is_all_day else f"{start_local.strftime('%H:%M')}-{end_local.strftime('%H:%M')}"
                )
                line = f"- {time_str}: {event.title}"
                if event.location:
                    line += f" @ {event.location}"
                if event.calendar_name:
                    line += f" [{event.calendar_name}]"
                lines.append(line)
            lines.append("")

        if lines and lines[-1] == "":
            lines.pop()

        if reminders:
            if lines:
                lines.append("")
            lines.append("**Reminders**")
            reminders_by_list: dict[str, list[Any]] = {}
            for reminder in reminders:
                key = reminder.list_name or "Reminders"
                reminders_by_list.setdefault(key, []).append(reminder)

            for list_name in sorted(reminders_by_list.keys()):
                lines.append(f"- {list_name}")
                for reminder in sorted(reminders_by_list[list_name], key=self._reminder_sort_key):
                    status = "done" if reminder.completed else "open"
                    due_text = self._format_reminder_due(reminder.due_date)
                    extra = f", due {due_text}" if due_text else ""
                    lines.append(f"  - {reminder.title} ({status}{extra})")

        return "\n".join(lines).strip()

    def _reminder_sort_key(self, reminder: Any) -> tuple[datetime, str]:
        due = reminder.due_date
        if due is None:
            return (datetime.max.replace(tzinfo=self._tz), reminder.title)
        due_local = self._ensure_timezone(due)
        return (due_local, reminder.title)

    def _format_reminder_due(self, due: datetime | None) -> str | None:
        if due is None:
            return None
        due_local = self._ensure_timezone(due)
        return due_local.strftime("%Y-%m-%d %H:%M")

    def _ensure_timezone(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self._tz)
        return value.astimezone(self._tz)

    @staticmethod
    def _promote_subheading(markdown: str) -> str:
        if not markdown:
            return markdown
        lines = markdown.splitlines()
        if not lines:
            return markdown
        first = lines[0].strip()
        if first.startswith("##"):
            heading = first.lstrip("# ").strip()
            lines[0] = f"**{heading}**"
        return "\n".join(line.rstrip() for line in lines).strip()

    @staticmethod
    def _drop_none(mapping: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in mapping.items() if value is not None}

    @staticmethod
    def _safe_int(value: Any, default: int | None = 0) -> int | None:
        try:
            if value is None:
                return default
            numeric = float(value)
            if math.isnan(numeric):
                return default
            return int(round(numeric))
        except Exception:
            return default

    @staticmethod
    def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
        try:
            if value is None:
                return default
            numeric = float(value)
            if math.isnan(numeric):
                return default
            return numeric
        except Exception:
            return default

    def _normalise_markdown(self, markdown: str | None) -> str | None:
        if markdown is None:
            return None
        cleaned = markdown.strip()
        return cleaned or None

    def _render_section(self, title: str, body_markdown: str) -> str:
        return f"### {title}\n\n{body_markdown}"

    def _to_jsonable(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return self._ensure_timezone(value).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if is_dataclass(value) and not isinstance(value, type):
            return {key: self._to_jsonable(val) for key, val in asdict(cast(Any, value)).items()}
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump(mode="json")
            except TypeError:
                return value.model_dump()
        if isinstance(value, dict):
            return {key: self._to_jsonable(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_jsonable(item) for item in value]
        return str(value)


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    clean = text.strip()
    if not clean:
        return 0
    return max(1, math.ceil(len(clean) / 4))


def _coerce_to_markdown_block(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, (list, tuple)):
        try:
            return json.dumps(content, indent=2, ensure_ascii=False, default=str)
        except TypeError:
            return "\n".join(str(item) for item in content)
    if isinstance(content, dict):
        try:
            return json.dumps(content, indent=2, ensure_ascii=False, default=str)
        except TypeError:
            return "\n".join(f"{key}: {value}" for key, value in content.items())
    return str(content)
