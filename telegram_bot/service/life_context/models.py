from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field, model_validator


class LifeContextMetric(str, Enum):
    NOTES = "notes"
    GARMIN = "garmin"
    CALENDAR = "calendar"
    CORRELATIONS = "correlations"
    VARIANCE = "variance"
    PERSISTENT_MEMORY = "persistent_memory"

    @classmethod
    def all_metrics(cls) -> frozenset[LifeContextMetric]:
        return frozenset(
            {
                cls.NOTES,
                cls.GARMIN,
                cls.CALENDAR,
                cls.CORRELATIONS,
                cls.VARIANCE,
                cls.PERSISTENT_MEMORY,
            }
        )


class LifeContextConfig(BaseModel):
    default_lookback_days: int = 7
    max_token_budget: int = 56000
    notes_limit: int | None = None
    calendar_limit: int | None = None
    correlation_limit: int = 5
    variance_limit: int = 3
    variance_min_score: float = 0.0


class LifeContextRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    metrics: frozenset[LifeContextMetric] = Field(default_factory=LifeContextMetric.all_metrics)
    max_token_budget: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise_metrics(cls, values: dict[str, Any]) -> dict[str, Any]:
        raw_metrics = values.get("metrics", "all")
        values["metrics"] = cls._parse_metrics(raw_metrics)
        return values

    @staticmethod
    def _parse_metrics(metrics: Any) -> frozenset[LifeContextMetric]:
        if metrics in (None, "all"):
            return LifeContextMetric.all_metrics()
        if isinstance(metrics, str):
            return frozenset({LifeContextMetric(metrics)})
        if isinstance(metrics, LifeContextMetric):
            return frozenset({metrics})
        if isinstance(metrics, Iterable):
            converted = []
            for item in metrics:
                if isinstance(item, LifeContextMetric):
                    converted.append(item)
                else:
                    converted.append(LifeContextMetric(item))
            return frozenset(converted)
        raise TypeError(f"Unsupported metrics value: {metrics!r}")


@dataclass(slots=True)
class LifeContextBundle:
    start_date: date
    end_date: date
    notes_by_date: dict[str, str] | None = None
    garmin: Any | None = None
    calendar: Any | None = None
    correlations: Any | None = None
    variance: Any | None = None
    persistent_memory: str | None = None


@dataclass(slots=True)
class LifeContextFormattedResponse:
    bundle: LifeContextBundle
    sections: dict[str, Any]
    rendered_markdown: str | None
    error: str | None = None
