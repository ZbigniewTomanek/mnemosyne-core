from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from loguru import logger

from telegram_bot.config import CorrelationEngineConfig

from .engine import CorrelationEngine
from .models import CorrelationEvent, CorrelationJobConfig, CorrelationRunRequest, CorrelationRunSummary


class EventSource(Protocol):
    async def fetch_events(self, job_config: CorrelationJobConfig) -> list[CorrelationEvent]:
        ...


class CorrelationJobRunner:
    """Coordinates fetching events and running the correlation engine."""

    def __init__(
        self,
        engine: CorrelationEngine,
        event_sources: Sequence[EventSource],
        config: CorrelationEngineConfig,
        user_id: int,
    ) -> None:
        self._engine = engine
        self._event_sources = tuple(event_sources)
        self._config = config
        self._user_id = user_id

    async def run(self) -> CorrelationRunSummary:
        job_config = self._config.to_job_config()
        logger.info(
            "Fetching events for correlation job (lookback={} days, sources={})",
            job_config.lookback_days,
            [type(source).__name__ for source in self._event_sources],
        )
        events, telemetry = await self._gather_events(job_config)
        if not events:
            logger.info("No events found for correlation window; returning empty summary")
            now = datetime.now(UTC)
            return CorrelationRunSummary(
                run_id=str(uuid4()),
                started_at=now,
                completed_at=now,
                user_id=self._user_id,
                window_days=job_config.lookback_days,
                results=[],
                discarded_events=[],
                telemetry={"reason": "no_events_in_window", **telemetry},
            )

        request = CorrelationRunRequest(user_id=self._user_id, config=job_config, events=events)
        summary = await self._engine.run(request)
        summary.telemetry.update(telemetry)
        return summary

    async def _gather_events(self, job_config: CorrelationJobConfig) -> tuple[list[CorrelationEvent], dict[str, Any]]:
        events: list[CorrelationEvent] = []
        source_counts: dict[str, int] = {}
        for source in self._event_sources:
            source_name = type(source).__name__
            try:
                source_events = await source.fetch_events(job_config)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception(
                    "Event source {} failed to fetch events: {}",
                    type(source).__name__,
                    exc,
                )
                continue
            source_counts[source_name] = source_counts.get(source_name, 0) + len(source_events)
            events.extend(source_events)

        if not events:
            return [], {"raw_event_count": 0, "deduplicated_event_count": 0, "per_source_counts": source_counts}

        # Deduplicate by event id while preserving latest occurrence
        deduped: dict[str, CorrelationEvent] = {}
        for event in events:
            deduped[event.id] = event

        # Sort by start time, then event ID for deterministic ordering.
        # Event IDs are stable (Garmin uses numeric IDs, calendar uses deterministic hash)
        sorted_events = sorted(deduped.values(), key=lambda event: (event.start, event.source, event.id))
        telemetry = {
            "raw_event_count": len(events),
            "deduplicated_event_count": len(sorted_events),
            "per_source_counts": source_counts,
        }
        return sorted_events, telemetry
