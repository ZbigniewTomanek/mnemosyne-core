"""Utilities for presenting correlation engine results in downstream prompts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from telegram_bot.service.db_service import ActivityImpactVarianceEntry, CorrelationEventRecord, CorrelationMetricRecord


def format_correlation_events(
    events: Sequence[CorrelationEventRecord],
    *,
    tz: Optional[ZoneInfo] = None,
    max_events: Optional[int] = None,
    include_supporting: bool = False,
) -> str:
    """Return a markdown-style summary of correlation events for LLM prompts.

    Args:
        events: Correlation events to summarise.
        tz: Optional timezone for rendering event timestamps.
        max_events: Optional limit of events to include (most recent first).
        include_supporting: When true, append serialised supporting evidence payloads.
    """
    if not events:
        return ""

    sorted_events = sorted(events, key=lambda event: event.start, reverse=True)
    if max_events is not None:
        sorted_events = sorted_events[:max_events]

    lines: list[str] = []
    for event in sorted_events:
        start_str = _format_timestamp(event.start, tz)
        end_str = _format_timestamp(event.end, tz)
        header = f"- {start_str} - {end_str} | {event.title} (source: {event.source})"
        if event.categories:
            header += f" | tags: {', '.join(sorted(event.categories))}"
        lines.append(header)

        for metric in event.metrics:
            metric_line = _format_metric_line(metric)
            lines.append(f"    {metric_line}")

        if include_supporting and event.supporting_evidence:
            lines.append(f"    supporting: {event.supporting_evidence}")

    return "\n".join(lines)


def format_activity_variances(
    variances: Sequence[ActivityImpactVarianceEntry],
    *,
    tz: Optional[ZoneInfo] = None,
    max_items: Optional[int] = None,
) -> str:
    """Return markdown summary of activity impact variance entries."""
    if not variances:
        return ""

    sorted_entries = sorted(variances, key=lambda entry: abs(entry.normalised_score), reverse=True)
    if max_items is not None:
        sorted_entries = sorted_entries[:max_items]

    lines: list[str] = []
    for entry in sorted_entries:
        title = entry.raw_title or entry.title_key
        metric_name = entry.metric.replace("_", " ").title()
        start = _format_timestamp(entry.window_start, tz)
        end = _format_timestamp(entry.window_end, tz)
        delta = entry.delta if entry.delta is not None else 0.0
        z_score = entry.normalised_score if entry.normalised_score is not None else 0.0
        baseline_mean = entry.baseline_mean if entry.baseline_mean is not None else None
        current_effect = entry.current_effect if entry.current_effect is not None else None
        trend = entry.trend or "stable"
        sample_count = entry.baseline_sample_count if entry.baseline_sample_count is not None else 0

        baseline_str = f"{baseline_mean:.2f}" if baseline_mean is not None else "n/a"
        current_str = f"{current_effect:.2f}" if current_effect is not None else "n/a"

        lines.append(
            f"- {start} -> {end} | {title} [{metric_name}] Δ {delta:+.2f} (z={z_score:+.2f}, trend {trend}) "
            f"baseline {baseline_str} -> {current_str} (n={sample_count})"
        )

    return "\n".join(lines)


def _format_timestamp(timestamp: datetime, tz: Optional[ZoneInfo]) -> str:
    """Format a timestamp for display.

    Args:
        timestamp: The timestamp to format (should be timezone-aware)
        tz: Optional timezone to convert to for display

    Note:
        If timestamp is naive (no timezone), it's assumed to already be in the target timezone
        and is labeled accordingly. This is defensive - all timestamps should be timezone-aware.
    """
    if tz is not None:
        if timestamp.tzinfo is None:
            # Defensive: assume naive timestamp is already in target timezone
            # In production, all timestamps should be timezone-aware
            timestamp = timestamp.replace(tzinfo=tz)
        else:
            # Normal case: convert to target timezone
            timestamp = timestamp.astimezone(tz)
    return timestamp.strftime("%Y-%m-%d %H:%M")


def _format_metric_line(metric: CorrelationMetricRecord) -> str:
    metric_name = metric.metric.replace("_", " ").title()
    delta = metric.effect_size
    symbol = {
        "increase": "increase",
        "decrease": "decrease",
        "neutral": "neutral",
    }.get(metric.effect_direction, metric.effect_direction)

    confidence_pct = f"{metric.confidence * 100:.0f}%"
    pieces = [
        f"{metric_name}: {symbol} ({delta:+.2f})",
        f"confidence {confidence_pct}",
        f"samples {metric.sample_count}",
    ]

    if metric.p_value is not None:
        pieces.append(f"p={metric.p_value:.3f}")
    if metric.baseline_mean is not None and metric.post_event_mean is not None:
        pieces.append(f"baseline {metric.baseline_mean:.2f} -> {metric.post_event_mean:.2f}")
    if metric.notes:
        pieces.append(f"notes: {metric.notes}")

    return " | ".join(pieces)
