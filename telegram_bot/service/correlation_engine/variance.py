from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal
from uuid import uuid4

from loguru import logger

from telegram_bot.service.db_service import ActivityImpactVarianceEntry, DBService, MetricObservationRecord

from .models import (
    ActivityImpactVariance,
    ActivityImpactVarianceConfig,
    BioSignalType,
    CorrelationEvent,
    CorrelationJobConfig,
    CorrelationRunSummary,
)

_EFFECT_SIZE_EPSILON = 0.01
_STD_EPSILON = 1e-6


class ActivityImpactVarianceService:
    """Analyse historical variance of similarly titled activities."""

    def __init__(
        self,
        db_service: DBService,
        *,
        clock: Callable[[], datetime] | None = None,
        title_normaliser: Callable[[str], str] | None = None,
    ) -> None:
        self._db_service = db_service
        self._clock = clock or (lambda: datetime.now(UTC))
        self._normalise_title = title_normaliser or self._default_title_normaliser

    async def compute_for_run(
        self, summary: CorrelationRunSummary, job_config: CorrelationJobConfig
    ) -> list[ActivityImpactVariance]:
        config = job_config.variance_analysis
        if not config.enabled or not summary.results:
            return []

        logger.debug(
            "Computing activity variance results",
            run_id=summary.run_id,
            lookback_days=config.lookback_days,
        )

        observations = self._db_service.fetch_metric_observations(lookback_days=config.lookback_days)
        history_index = self._build_history_index(observations)
        now = self._clock()
        window_start = now - timedelta(days=config.lookback_days)
        window_end = now
        config_hash = self._config_hash(config)

        variance_results: list[ActivityImpactVariance] = []

        for result in summary.results:
            title_key = self._normalise_title(result.event.title)
            metadata_payload = {
                "categories": sorted(result.event.categories),
                "metadata": result.event.metadata,
            }
            metadata_json = json.dumps(metadata_payload) if any(metadata_payload.values()) else None

            for metric_effect in result.evaluated_metrics:
                metric_name = metric_effect.metric.value

                if self._db_service.activity_variance_exists(
                    event_id=result.event.id,
                    metric=metric_name,
                    config_hash=config_hash,
                ):
                    existing_entry = self._db_service.get_activity_variance(
                        event_id=result.event.id,
                        metric=metric_name,
                        config_hash=config_hash,
                    )
                    if existing_entry is not None:
                        variance_results.append(
                            self._entry_to_variance(
                                entry=existing_entry,
                                event=result.event,
                                metric=metric_effect.metric,
                                summary_run_id=summary.run_id,
                                config=config,
                            )
                        )
                    else:  # pragma: no cover - defensive
                        logger.debug(
                            "Variance entry reported as existing but not retrievable",
                            event_id=result.event.id,
                            metric=metric_name,
                        )
                    continue

                metric_key = (title_key, metric_name)
                baseline_records = history_index.get(metric_key, [])
                baseline_values = [
                    obs.effect_size
                    for obs in baseline_records
                    if not (obs.event_id == result.event.id and obs.run_id == summary.run_id)
                ]

                if len(baseline_values) < config.min_samples:
                    logger.debug(
                        "Skipping variance calculation due to insufficient baseline",
                        event_id=result.event.id,
                        metric=metric_effect.metric.value,
                        baseline_samples=len(baseline_values),
                        required=config.min_samples,
                    )
                    continue

                baseline_mean = statistics.fmean(baseline_values)
                baseline_stddev = statistics.pstdev(baseline_values, baseline_mean) if len(baseline_values) > 1 else 0.0
                delta = metric_effect.effect_size - baseline_mean
                normalised_score = self._score_delta(delta, baseline_stddev, baseline_mean)
                trend = self._trend_direction(delta)
                is_alert = abs(normalised_score) >= config.min_score_for_alert

                variance = ActivityImpactVariance(
                    run_id=summary.run_id,
                    event_id=result.event.id,
                    title_key=title_key,
                    raw_title=result.event.title,
                    metric=metric_effect.metric,
                    baseline_mean=baseline_mean,
                    baseline_stddev=baseline_stddev,
                    baseline_sample_count=len(baseline_values),
                    current_effect=metric_effect.effect_size,
                    delta=delta,
                    normalised_score=normalised_score,
                    trend=trend,
                    observed_at=result.event.end,
                    metadata=metadata_payload,
                    is_alert=is_alert,
                    config_hash=config_hash,
                )
                variance_results.append(variance)

                variance_entry = ActivityImpactVarianceEntry(
                    variance_id=str(uuid4()),
                    run_id=summary.run_id,
                    event_id=result.event.id,
                    title_key=title_key,
                    raw_title=result.event.title,
                    metric=metric_effect.metric.value,
                    window_start=window_start,
                    window_end=window_end,
                    baseline_mean=baseline_mean,
                    baseline_stddev=baseline_stddev,
                    baseline_sample_count=len(baseline_values),
                    current_effect=metric_effect.effect_size,
                    delta=delta,
                    normalised_score=normalised_score,
                    trend=trend,
                    metadata_json=metadata_json,
                    config_hash=config_hash,
                )
                self._db_service.add_activity_variance(variance_entry)

        variance_results.sort(key=lambda item: abs(item.normalised_score), reverse=True)
        return variance_results

    @staticmethod
    def _default_title_normaliser(title: str) -> str:
        collapsed = " ".join(title.strip().split())
        return collapsed.lower().replace(" ", "-")

    @staticmethod
    def _trend_direction(delta: float) -> Literal["increase", "decrease", "neutral"]:
        if delta > _EFFECT_SIZE_EPSILON:
            return "increase"
        if delta < -_EFFECT_SIZE_EPSILON:
            return "decrease"
        return "neutral"

    @staticmethod
    def _score_delta(delta: float, stddev: float, baseline_mean: float) -> float:
        if stddev >= _STD_EPSILON:
            return delta / stddev
        scale = max(abs(baseline_mean), 1.0)
        if scale < _STD_EPSILON:
            return 0.0
        return delta / scale

    def _build_history_index(
        self, observations: list[MetricObservationRecord]
    ) -> dict[tuple[str, str], list[MetricObservationRecord]]:
        index: dict[tuple[str, str], list[MetricObservationRecord]] = defaultdict(list)
        for obs in observations:
            key = (self._normalise_title(obs.title), obs.metric)
            index[key].append(obs)
        return index

    @staticmethod
    def _config_hash(config: ActivityImpactVarianceConfig) -> str:
        payload_dict = config.model_dump()
        payload = json.dumps(payload_dict, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _entry_to_variance(
        *,
        entry: ActivityImpactVarianceEntry,
        event: CorrelationEvent,
        metric: BioSignalType,
        summary_run_id: str,
        config: ActivityImpactVarianceConfig,
    ) -> ActivityImpactVariance:
        metadata_payload: dict[str, Any] = {}
        if entry.metadata_json:
            try:
                metadata_payload = json.loads(entry.metadata_json)
            except json.JSONDecodeError:  # pragma: no cover - defensive
                logger.warning("Failed to decode variance metadata for event {}", entry.event_id)

        is_alert = abs(entry.normalised_score) >= config.min_score_for_alert

        # Validate trend value from database
        trend_value = entry.trend
        if trend_value not in ("increase", "decrease", "neutral"):
            logger.warning("Invalid trend value in database: {}, defaulting to neutral", trend_value)
            trend_value = "neutral"

        return ActivityImpactVariance(
            run_id=summary_run_id,
            event_id=event.id,
            title_key=entry.title_key,
            raw_title=event.title,
            metric=metric,
            baseline_mean=entry.baseline_mean,
            baseline_stddev=entry.baseline_stddev,
            baseline_sample_count=entry.baseline_sample_count,
            current_effect=entry.current_effect,
            delta=entry.delta,
            normalised_score=entry.normalised_score,
            trend=trend_value,  # type: ignore[arg-type]  # validated above
            observed_at=event.end,
            metadata=metadata_payload,
            is_alert=is_alert,
            config_hash=entry.config_hash,
        )
