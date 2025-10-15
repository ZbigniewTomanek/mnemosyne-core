from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from scipy.stats import t as student_t


@dataclass
class StatisticalTestResult:
    effect_size: float
    baseline_mean: float
    post_event_mean: float
    test_statistic: float
    degrees_of_freedom: float
    p_value: float
    confidence: float


class StatisticalTest(Protocol):
    def evaluate(self, baseline: Sequence[float], effect: Sequence[float]) -> StatisticalTestResult: ...


class WelchTTest:
    """Welch's t-test with optional scipy-backed p-values."""

    def evaluate(self, baseline: Sequence[float], effect: Sequence[float]) -> StatisticalTestResult:
        if not baseline or not effect:
            raise ValueError("Both baseline and effect samples are required for statistical testing")

        baseline_mean = statistics.fmean(baseline)
        effect_mean = statistics.fmean(effect)
        effect_size = effect_mean - baseline_mean

        if len(baseline) > 1:
            baseline_var = statistics.pvariance(baseline, baseline_mean)
        else:
            baseline_var = 0.0
        if len(effect) > 1:
            effect_var = statistics.pvariance(effect, effect_mean)
        else:
            effect_var = 0.0

        se = math.sqrt((baseline_var / len(baseline)) + (effect_var / len(effect)))
        if se == 0:
            test_stat = 0.0
            p_value = 1.0
            df = 1.0
        else:
            test_stat = effect_size / se
            df = self._welch_satterthwaite_df(baseline_var, len(baseline), effect_var, len(effect))
            p_value = self._two_tailed_p_value(abs(test_stat), df)

        confidence = max(0.0, 1.0 - p_value)

        return StatisticalTestResult(
            effect_size=effect_size,
            baseline_mean=baseline_mean,
            post_event_mean=effect_mean,
            test_statistic=test_stat,
            degrees_of_freedom=df,
            p_value=p_value,
            confidence=confidence,
        )

    @staticmethod
    def _welch_satterthwaite_df(var1: float, n1: int, var2: float, n2: int) -> float:
        if n1 <= 1 and n2 <= 1:
            return 1.0
        numerator = (var1 / n1 + var2 / n2) ** 2
        denominator = 0.0
        if n1 > 1 and var1 > 0:
            denominator += (var1**2) / (n1**2 * (n1 - 1))
        if n2 > 1 and var2 > 0:
            denominator += (var2**2) / (n2**2 * (n2 - 1))
        if denominator == 0.0:
            return float(max(n1 - 1, n2 - 1, 1))
        return numerator / denominator

    @staticmethod
    def _two_tailed_p_value(t_value: float, degrees_of_freedom: float) -> float:
        return float(student_t.sf(t_value, degrees_of_freedom) * 2)
