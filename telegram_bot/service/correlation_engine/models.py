from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, field_validator


class BioSignalType(str, Enum):
    BODY_BATTERY = "body_battery"
    STRESS = "stress"
    HEART_RATE = "heart_rate"
    BREATHING_RATE = "breathing_rate"
    SLEEP = "sleep"


class WindowConfig(BaseModel):
    baseline: timedelta = Field(default=timedelta(hours=6))
    post_event: timedelta = Field(default=timedelta(hours=3))
    sampling_freq: str = Field(default="5min")

    @field_validator("baseline", "post_event")
    @classmethod
    def validate_positive_timedelta(cls, v: timedelta) -> timedelta:
        if v.total_seconds() <= 0:
            raise ValueError(f"Window duration must be positive, got {v}")
        return v

    @field_validator("sampling_freq")
    @classmethod
    def validate_sampling_frequency(cls, v: str) -> str:
        try:
            pd.tseries.frequencies.to_offset(v)
        except ValueError as e:
            raise ValueError(f"Invalid sampling frequency '{v}': {e}. Examples: '1min', '5min', '1h'")
        return v


class MetricThreshold(BaseModel):
    min_delta: float = Field(default=5.0, ge=0.0)
    min_samples: int = Field(default=5, gt=0)
    min_confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ActivityImpactVarianceConfig(BaseModel):
    enabled: bool = True
    lookback_days: int = Field(default=30, gt=0)
    min_samples: int = Field(default=3, ge=1)
    min_score_for_alert: float = Field(default=1.0, ge=0.0)
    max_alerts: int = Field(default=3, ge=0)


class GarminActivitySourceConfig(BaseModel):
    enabled: bool = True
    min_duration_minutes: int = 20
    min_moving_ratio: float = 0.5
    min_hr_zone45_seconds: int = 0
    include_sports: Optional[set[str]] = None
    exclude_sports: Optional[set[str]] = None
    metadata_fields: Sequence[str] = Field(
        default_factory=lambda: [
            "activityType",
            "activityName",
            "distance",
            "elapsedDuration",
            "movingDuration",
            "calories",
            "averageHR",
            "maxHR",
            "hrZone4Seconds",
            "hrZone5Seconds",
            "Aerobic_Training",
            "Anaerobic_Training",
            "Sport",
            "Sub_Sport",
            "locationName",
        ]
    )


class CalendarEventSourceConfig(BaseModel):
    enabled: bool = True
    calendar_filters: Optional[list[str]] = None


class CorrelationSourcesConfig(BaseModel):
    calendar: CalendarEventSourceConfig = Field(default_factory=CalendarEventSourceConfig)
    garmin_activity: GarminActivitySourceConfig = Field(default_factory=GarminActivitySourceConfig)
    cache_timeout_hours: int = Field(default=1, gt=0, description="Cache timeout for Garmin data exports in hours")


class SleepCorrelationConfig(BaseModel):
    enabled: bool = True
    baseline_nights: int = 5
    lookahead_hours: int = 36
    main_sleep_only: bool = True
    min_sleep_duration_minutes: int = 240
    metrics: dict[BioSignalType, MetricThreshold] = Field(
        default_factory=lambda: {
            BioSignalType.SLEEP: MetricThreshold(min_delta=15.0, min_samples=2, min_confidence=0.9),
            BioSignalType.BODY_BATTERY: MetricThreshold(min_delta=10.0, min_samples=2, min_confidence=0.85),
        }
    )


class CorrelationFetchConfig(BaseModel):
    """Shared configuration for fetching and displaying correlation events across different surfaces."""

    lookback_days: int = Field(default=7, gt=0, description="Number of days to look back for correlation events")
    max_events: int = Field(default=6, gt=0, description="Maximum number of correlation events to fetch")


class CorrelationJobConfig(BaseModel):
    lookback_days: int = Field(default=7)
    timezone: str = Field(default="UTC")
    metrics: dict[BioSignalType, MetricThreshold] = Field(default_factory=dict)
    windows: WindowConfig = Field(default_factory=WindowConfig)
    sources: CorrelationSourcesConfig = Field(default_factory=CorrelationSourcesConfig)
    sleep_analysis: SleepCorrelationConfig = Field(default_factory=SleepCorrelationConfig)
    variance_analysis: ActivityImpactVarianceConfig = Field(default_factory=ActivityImpactVarianceConfig)


class CorrelationEvent(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    source: Literal["calendar", "obsidian", "garmin_activity", "manual"]
    categories: set[str] = Field(default_factory=set)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimeSeriesPoint(BaseModel):
    ts: datetime
    value: float


class MetricWindowObservation(BaseModel):
    metric: BioSignalType
    baseline_points: list[TimeSeriesPoint]
    post_event_points: list[TimeSeriesPoint]
    observation_start: datetime
    observation_end: datetime


class MetricEffect(BaseModel):
    metric: BioSignalType
    effect_size: float
    effect_direction: Literal["increase", "decrease", "neutral"]
    confidence: float
    p_value: float
    sample_count: int
    baseline_mean: Optional[float] = None
    post_event_mean: Optional[float] = None
    notes: Optional[str] = None
    raw_observation: Optional[MetricWindowObservation] = None


class EventCorrelationResult(BaseModel):
    event: CorrelationEvent
    evaluated_metrics: list[MetricEffect] = Field(default_factory=list)
    triggered_metrics: list[MetricEffect] = Field(default_factory=list)
    overall_confidence: float = 0.0
    supporting_evidence: dict[str, Any] = Field(default_factory=dict)


class CorrelationRunRequest(BaseModel):
    user_id: int
    config: CorrelationJobConfig
    events: list[CorrelationEvent]


class ActivityImpactVariance(BaseModel):
    run_id: str
    event_id: str
    title_key: str
    raw_title: str
    metric: BioSignalType
    baseline_mean: float
    baseline_stddev: float
    baseline_sample_count: int
    current_effect: float
    delta: float
    normalised_score: float
    trend: Literal["increase", "decrease", "neutral"]
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_alert: bool = False
    config_hash: str


class CorrelationRunSummary(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime
    user_id: int
    window_days: int
    results: list[EventCorrelationResult]
    discarded_events: list[str] = Field(default_factory=list)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    variance_results: list[ActivityImpactVariance] = Field(default_factory=list)
