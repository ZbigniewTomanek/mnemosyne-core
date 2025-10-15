"""
Data models for the Garmin data analysis framework.

This module provides Pydantic models for:
- Core metrics outputs (sleep, recovery, etc.)
- Baseline data representation
- Interpretation results
- Insight and recommendation structures
"""

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BaselineStatus(str, Enum):
    """Status of a metric relative to its baseline."""

    NORMAL = "normal"  # Within normal range
    OPTIMAL = "optimal"  # Better than normal (in a good way)
    SLIGHT_DEVIATION = "slight_deviation"  # Slight deviation from normal
    CONCERNING = "concerning"  # Concerning deviation from normal
    NO_BASELINE = "no_baseline"  # No baseline available


class BaselineData(BaseModel):
    """Baseline data for a metric."""

    mean: float
    std_dev: float
    lookback_days: int = 30


class MetricWithBaseline(BaseModel):
    """A metric value with its baseline and status."""

    value: float
    baseline_mean: Optional[float] = None
    baseline_std_dev: Optional[float] = None
    z_score: Optional[float] = None
    status: BaselineStatus = BaselineStatus.NO_BASELINE


# Sleep metrics models


class SleepMetrics(BaseModel):
    """Core sleep metrics."""

    date: date
    total_sleep_seconds: Optional[int] = None  # Total sleep time in seconds
    deep_sleep_seconds: Optional[int] = None  # Deep sleep time in seconds
    light_sleep_seconds: Optional[int] = None  # Light sleep time in seconds
    rem_sleep_seconds: Optional[int] = None  # REM sleep time in seconds
    awake_seconds: Optional[int] = None  # Awake time in seconds

    sleep_efficiency_pct: Optional[float] = None  # Sleep efficiency (%)
    waso_seconds: Optional[int] = None  # Wake after sleep onset in seconds

    deep_sleep_pct: Optional[float] = None  # % of sleep in deep stage
    light_sleep_pct: Optional[float] = None  # % of sleep in light stage
    rem_sleep_pct: Optional[float] = None  # % of sleep in REM stage

    avg_sleep_stress: Optional[float] = None  # Average stress during sleep

    bedtime_timestamp: Optional[int] = None  # Start of sleep in Unix timestamp (ms)
    waketime_timestamp: Optional[int] = None  # End of sleep in Unix timestamp (ms)


class SleepMetricsWithBaselines(BaseModel):
    """Sleep metrics with baselines and status."""

    date: date
    total_sleep_time: MetricWithBaseline
    sleep_efficiency: MetricWithBaseline
    waso: Optional[MetricWithBaseline] = None
    deep_sleep_pct: Optional[MetricWithBaseline] = None
    rem_sleep_pct: Optional[MetricWithBaseline] = None
    avg_sleep_stress: Optional[MetricWithBaseline] = None


# Recovery and ANS metrics models


class RecoveryMetrics(BaseModel):
    """Core recovery and ANS metrics."""

    date: date
    resting_heart_rate: Optional[int] = None  # RHR in BPM
    hrv_rmssd: Optional[float] = None  # HRV RMSSD value
    hrv_7day_avg: Optional[float] = None  # 7-day rolling avg of HRV

    body_battery_max: Optional[int] = None  # Max Body Battery value
    body_battery_min: Optional[int] = None  # Min Body Battery value
    body_battery_charged: Optional[int] = None  # How much BB charged
    body_battery_drained: Optional[int] = None  # How much BB drained

    avg_stress_level: Optional[float] = None  # Average stress level for the day


class RecoveryMetricsWithBaselines(BaseModel):
    """Recovery metrics with baselines and status."""

    date: date
    resting_heart_rate: MetricWithBaseline
    hrv_rmssd: Optional[MetricWithBaseline] = None
    body_battery_max: Optional[MetricWithBaseline] = None
    body_battery_charged: Optional[MetricWithBaseline] = None
    avg_stress_level: Optional[MetricWithBaseline] = None


# Interpretation and insight models


class InterpretationCategory(str, Enum):
    """Categories for health interpretations."""

    RECOVERY = "recovery"
    SLEEP_QUALITY = "sleep_quality"
    STRESS = "stress"
    READINESS = "readiness"
    FATIGUE = "fatigue"
    TRAINING = "training"
    GENERAL = "general"


class Interpretation(BaseModel):
    """An interpretation of health metrics."""

    category: InterpretationCategory
    summary: str
    confidence: float = 1.0  # 0.0 to 1.0
    details: Dict[str, Any] = Field(default_factory=dict)
    supporting_metrics: List[str] = Field(default_factory=list)


class InterpretationResult(BaseModel):
    """Result of the interpretation engine."""

    date: date
    interpretations: List[Interpretation] = Field(default_factory=list)
    readiness_score: Optional[float] = None  # 0-100 score
    recovery_status: Optional[str] = None  # Overall recovery status


class InsightPriority(int, Enum):
    """Priority levels for insights."""

    HIGH = 1
    MEDIUM = 2
    LOW = 3


class ActionableInsight(BaseModel):
    """An actionable insight or recommendation."""

    category: str
    title: str
    text: str
    priority: InsightPriority = InsightPriority.MEDIUM
    tags: List[str] = Field(default_factory=list)


class DailyInsights(BaseModel):
    """Daily insights and recommendations."""

    date: date
    insights: List[ActionableInsight] = Field(default_factory=list)
    summary: str = ""
