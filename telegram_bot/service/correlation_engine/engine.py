from __future__ import annotations

import asyncio
import inspect
import json
import statistics
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Optional, Protocol
from uuid import uuid4

from loguru import logger

from telegram_bot.service.db_service import (
    CorrelationEventEntry,
    CorrelationMetricEntry,
    CorrelationRunEntry,
    DBService,
)

from .models import (
    BioSignalType,
    CorrelationEvent,
    CorrelationJobConfig,
    CorrelationRunRequest,
    CorrelationRunSummary,
    EventCorrelationResult,
    MetricEffect,
    MetricThreshold,
    MetricWindowObservation,
    TimeSeriesPoint,
)
from .sleep import SLEEP_METRIC_FIELDS, SleepAnalysisService, SleepMatch, serialize_session
from .stats import StatisticalTest
from .variance import ActivityImpactVarianceService

# Minimum absolute effect size to classify as increase/decrease (avoid classifying noise as signal)
_EFFECT_SIZE_EPSILON = 0.01


_SLEEP_PRIMARY_METRIC_MAP: dict[BioSignalType, str] = {
    BioSignalType.SLEEP: "sleepScore",
    BioSignalType.BODY_BATTERY: "bodyBatteryChange",
    BioSignalType.STRESS: "avgSleepStress",
    BioSignalType.HEART_RATE: "restingHeartRate",
}


class MetricSource(Protocol):
    async def fetch_series(
        self, metric: BioSignalType, start: datetime, end: datetime, sample_frequency: str
    ) -> list[TimeSeriesPoint]:
        ...


class CorrelationPublisher(Protocol):
    async def publish(self, summary: CorrelationRunSummary) -> None:  # pragma: no cover
        ...


class CorrelationEngine:
    def __init__(
        self,
        metric_source: MetricSource,
        db_service: DBService,
        stats_calculator: StatisticalTest,
        publishers: Optional[Sequence[CorrelationPublisher]] = None,
        sleep_service: Optional[SleepAnalysisService] = None,
        variance_service: Optional[ActivityImpactVarianceService] = None,
    ) -> None:
        self._metric_source = metric_source
        self._db_service = db_service
        self._stats_calculator = stats_calculator
        self._publishers = list(publishers or [])
        self._sleep_service = sleep_service
        self._variance_service = variance_service

    async def run(self, request: CorrelationRunRequest) -> CorrelationRunSummary:
        run_id = str(uuid4())
        started_at = datetime.now(UTC)
        start_time = time.perf_counter()

        logger.info(
            "Starting correlation run",
            run_id=run_id,
            user_id=request.user_id,
            event_count=len(request.events),
            lookback_days=request.config.lookback_days,
        )

        results: list[EventCorrelationResult] = []
        discarded_events: list[str] = []

        prepare_fn = getattr(self._metric_source, "prepare", None)
        if prepare_fn is not None:
            preparation = prepare_fn(request)
            if inspect.isawaitable(preparation):
                await preparation

        sleep_prepare = getattr(self._sleep_service, "prepare", None)
        if sleep_prepare is not None:
            await sleep_prepare(request)

        for event in request.events:
            try:
                result = await self._process_event(event, request.config)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Correlation processing failed for event {}: {}", event.id, exc)
                discarded_events.append(event.id)
                continue

            if result is None:
                discarded_events.append(event.id)
                continue

            results.append(result)

        completed_at = datetime.now(UTC)
        duration = time.perf_counter() - start_time

        summary = CorrelationRunSummary(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            user_id=request.user_id,
            window_days=request.config.lookback_days,
            results=results,
            discarded_events=discarded_events,
        )

        await self._persist_results(summary, request)

        if self._variance_service is not None:
            try:
                variance_results = await self._variance_service.compute_for_run(summary, request.config)
                summary.variance_results = variance_results
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Variance analysis failed for run {}: {}", summary.run_id, exc)

        await self._publish(summary)

        logger.info(
            "Completed correlation run",
            run_id=run_id,
            duration_sec=round(duration, 2),
            results=len(results),
            discarded=len(discarded_events),
        )
        return summary

    async def _process_event(
        self, event: CorrelationEvent, config: CorrelationJobConfig
    ) -> Optional[EventCorrelationResult]:
        window = config.windows
        baseline_start = event.start - window.baseline
        baseline_end = event.start
        effect_start = event.start
        effect_end = event.end + window.post_event

        evaluated: list[MetricEffect] = []
        triggered: list[MetricEffect] = []
        supporting_evidence: dict[str, Any] = {}

        for metric, threshold in config.metrics.items():
            effect = await self._evaluate_metric(
                metric=metric,
                threshold=threshold,
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                effect_start=effect_start,
                effect_end=effect_end,
                sample_frequency=window.sampling_freq,
            )
            if effect is None:
                continue

            evaluated.append(effect)
            if effect.effect_direction != "neutral" and effect.confidence >= threshold.min_confidence:
                if abs(effect.effect_size) >= threshold.min_delta and effect.sample_count >= threshold.min_samples:
                    triggered.append(effect)

        sleep_effects, sleep_evidence = self._evaluate_sleep_metrics(event, config)
        for effect, threshold in sleep_effects:
            evaluated.append(effect)
            if effect.effect_direction != "neutral" and effect.confidence >= threshold.min_confidence:
                if abs(effect.effect_size) >= threshold.min_delta and effect.sample_count >= threshold.min_samples:
                    triggered.append(effect)
        if sleep_evidence:
            supporting_evidence["sleep_analysis"] = sleep_evidence

        overall_confidence = max((eff.confidence for eff in triggered), default=0.0)
        if not evaluated and not triggered:
            logger.debug("Event discarded - no metrics evaluated", event_id=event.id, event_title=event.title)
            return None

        return EventCorrelationResult(
            event=event,
            evaluated_metrics=evaluated,
            triggered_metrics=triggered,
            overall_confidence=overall_confidence,
            supporting_evidence=supporting_evidence,
        )

    async def _evaluate_metric(
        self,
        metric: BioSignalType,
        threshold: MetricThreshold,
        baseline_start: datetime,
        baseline_end: datetime,
        effect_start: datetime,
        effect_end: datetime,
        sample_frequency: str,
    ) -> Optional[MetricEffect]:
        baseline_points = await self._metric_source.fetch_series(metric, baseline_start, baseline_end, sample_frequency)
        effect_points = await self._metric_source.fetch_series(metric, effect_start, effect_end, sample_frequency)

        baseline_values = [pt.value for pt in baseline_points if pt.value is not None]
        effect_values = [pt.value for pt in effect_points if pt.value is not None]

        if len(effect_values) < threshold.min_samples or len(baseline_values) == 0:
            logger.debug(
                "Insufficient samples for metric",
                metric=metric.value,
                baseline_samples=len(baseline_values),
                effect_samples=len(effect_values),
                min_required=threshold.min_samples,
            )
            return None

        stats_result = self._stats_calculator.evaluate(baseline_values, effect_values)

        logger.debug(
            "Metric evaluation",
            metric=metric.value,
            baseline_samples=len(baseline_values),
            effect_samples=len(effect_values),
            effect_size=round(stats_result.effect_size, 2),
            confidence=round(stats_result.confidence, 3),
            p_value=round(stats_result.p_value, 4),
        )

        direction: Literal["increase", "decrease", "neutral"]
        if stats_result.effect_size > _EFFECT_SIZE_EPSILON:
            direction = "increase"
        elif stats_result.effect_size < -_EFFECT_SIZE_EPSILON:
            direction = "decrease"
        else:
            direction = "neutral"

        observation = MetricWindowObservation(
            metric=metric,
            baseline_points=baseline_points,
            post_event_points=effect_points,
            observation_start=effect_start,
            observation_end=effect_end,
        )

        return MetricEffect(
            metric=metric,
            effect_size=stats_result.effect_size,
            effect_direction=direction,
            confidence=stats_result.confidence,
            p_value=stats_result.p_value,
            sample_count=len(effect_values),
            baseline_mean=stats_result.baseline_mean,
            post_event_mean=stats_result.post_event_mean,
            raw_observation=observation,
        )

    def _evaluate_sleep_metrics(
        self, event: CorrelationEvent, config: CorrelationJobConfig
    ) -> tuple[list[tuple[MetricEffect, MetricThreshold]], dict[str, Any]]:
        if self._sleep_service is None:
            return [], {}
        sleep_config = config.sleep_analysis
        if not sleep_config.enabled or not sleep_config.metrics:
            return [], {}

        match = self._sleep_service.match_event(event, sleep_config)
        if match is None:
            return [], {}

        evidence = self._build_sleep_evidence(match)
        effects: list[tuple[MetricEffect, MetricThreshold]] = []

        for metric, threshold in sleep_config.metrics.items():
            metric_key = _SLEEP_PRIMARY_METRIC_MAP.get(metric)
            if metric_key is None:
                continue

            baseline_values = [
                float(value)
                for session in match.baseline_sessions
                if (value := session.metrics.get(metric_key)) is not None
            ]
            effect_value = match.matched_session.metrics.get(metric_key)

            if effect_value is None or not baseline_values:
                continue

            stats_result = self._stats_calculator.evaluate(baseline_values, [float(effect_value)])
            direction = self._effect_direction(stats_result.effect_size)
            confidence = self._sleep_confidence(
                baseline_values, float(effect_value), stats_result.confidence, threshold
            )

            effect = MetricEffect(
                metric=metric,
                effect_size=stats_result.effect_size,
                effect_direction=direction,
                confidence=confidence,
                p_value=stats_result.p_value,
                sample_count=len(baseline_values) + 1,
                baseline_mean=stats_result.baseline_mean,
                post_event_mean=stats_result.post_event_mean,
                notes=f"sleep_analysis:{metric_key}",
            )
            effects.append((effect, threshold))

        return effects, evidence

    def _build_sleep_evidence(self, match: SleepMatch) -> dict[str, Any]:
        summary: dict[str, dict[str, float]] = {}
        for key in SLEEP_METRIC_FIELDS:
            baseline_values = [
                float(value) for session in match.baseline_sessions if (value := session.metrics.get(key)) is not None
            ]
            effect_value = match.matched_session.metrics.get(key)
            if effect_value is None or not baseline_values:
                continue

            baseline_mean = statistics.fmean(baseline_values) if len(baseline_values) > 1 else baseline_values[0]
            summary[key] = {
                "baseline_mean": baseline_mean,
                "effect": float(effect_value),
                "delta": float(effect_value) - baseline_mean,
            }

        return {
            "matched_session": serialize_session(match.matched_session),
            "baseline_sessions": [serialize_session(session) for session in match.baseline_sessions],
            "metric_summary": summary,
        }

    @staticmethod
    def _effect_direction(effect_size: float) -> Literal["increase", "decrease", "neutral"]:
        if effect_size > _EFFECT_SIZE_EPSILON:
            return "increase"
        if effect_size < -_EFFECT_SIZE_EPSILON:
            return "decrease"
        return "neutral"

    @staticmethod
    def _sleep_confidence(
        baseline_values: Sequence[float],
        effect_value: float,
        stats_confidence: float,
        threshold: MetricThreshold,
    ) -> float:
        if len(baseline_values) >= 2:
            return stats_confidence

        baseline_value = float(baseline_values[0])
        delta = abs(effect_value - baseline_value)
        scale = max(abs(baseline_value), threshold.min_delta, 1.0)
        heuristic = min(0.99, delta / scale)
        return max(stats_confidence, heuristic)

    async def _persist_results(self, summary: CorrelationRunSummary, request: CorrelationRunRequest) -> None:
        """Persist correlation results to database in a thread pool to avoid blocking the event loop."""
        try:
            await asyncio.to_thread(self._persist_results_sync, summary, request)
        except Exception as exc:
            logger.exception("Failed to persist correlation results for run {}: {}", summary.run_id, exc)

    def _persist_results_sync(self, summary: CorrelationRunSummary, request: CorrelationRunRequest) -> None:
        """Synchronous database persistence logic."""
        config_json = request.config.model_dump_json()
        run_entry = CorrelationRunEntry(
            run_id=summary.run_id,
            user_id=request.user_id,
            started_at=summary.started_at,
            completed_at=summary.completed_at,
            window_days=summary.window_days,
            config_json=config_json,
        )
        self._db_service.add_correlation_run(run_entry)

        for result in summary.results:
            event = result.event
            metadata_payload = {
                "metadata": event.metadata,
                "categories": sorted(event.categories),
            }
            metadata_json = json.dumps(metadata_payload) if any(metadata_payload.values()) else None
            supporting_json = json.dumps(result.supporting_evidence) if result.supporting_evidence else None
            event_entry = CorrelationEventEntry(
                run_id=summary.run_id,
                event_id=event.id,
                source=event.source,
                title=event.title,
                start=event.start,
                end=event.end,
                metadata_json=metadata_json,
                supporting_json=supporting_json,
            )
            self._db_service.add_correlation_event(event_entry)

            triggered_ids = {id(effect) for effect in result.triggered_metrics}
            for metric_effect in result.evaluated_metrics:
                metric_name = metric_effect.metric.value
                is_triggered = id(metric_effect) in triggered_ids
                if self._db_service.correlation_metric_exists(event_id=event.id, metric=metric_name):
                    logger.info(
                        "Skipping duplicate correlation metric",
                        event_id=event.id,
                        metric=metric_name,
                        is_triggered=is_triggered,
                    )
                    continue

                metric_entry = CorrelationMetricEntry(
                    run_id=summary.run_id,
                    event_id=event.id,
                    metric=metric_name,
                    effect_size=metric_effect.effect_size,
                    effect_direction=metric_effect.effect_direction,
                    confidence=metric_effect.confidence,
                    p_value=metric_effect.p_value,
                    sample_count=metric_effect.sample_count,
                    baseline_mean=metric_effect.baseline_mean,
                    post_event_mean=metric_effect.post_event_mean,
                    notes=metric_effect.notes,
                    is_triggered=is_triggered,
                )
                self._db_service.add_correlation_metric(metric_entry)

    async def _publish(self, summary: CorrelationRunSummary) -> None:
        if not self._publishers:
            return

        async def _run_publisher(publisher: CorrelationPublisher) -> None:
            try:
                result = publisher.publish(summary)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.exception("Publisher {} failed: {}", type(publisher).__name__, exc)

        results = await asyncio.gather(
            *[_run_publisher(publisher) for publisher in self._publishers], return_exceptions=True
        )

        failures = [r for r in results if isinstance(r, Exception)]
        if failures:
            logger.warning("Correlation run {} had {} publisher failures", summary.run_id, len(failures))
