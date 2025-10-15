"""
Baseline calculator for Garmin metrics.

This module provides functionality for calculating personal baselines from historical
Garmin health data, allowing for meaningful comparison of daily metrics against
a user's typical values.
"""

import datetime as dt
import json
import math
from pathlib import Path
from typing import Optional, TypeVar, Union

import duckdb
from loguru import logger

from telegram_bot.service.garmin_analysis.common.constants import BaselineThresholds
from telegram_bot.service.garmin_analysis.common.data_models import (
    BaselineData,
    BaselineStatus,
    MetricWithBaseline,
    RecoveryMetrics,
    RecoveryMetricsWithBaselines,
    SleepMetrics,
    SleepMetricsWithBaselines,
)
from telegram_bot.service.garmin_analysis.core_metrics.recovery_metrics import RecoveryMetricsCalculator
from telegram_bot.service.garmin_analysis.core_metrics.sleep_metrics import SleepMetricsCalculator

# Generic type for metrics
MetricsT = TypeVar("MetricsT", SleepMetrics, RecoveryMetrics)
MetricsWithBaselinesT = TypeVar("MetricsWithBaselinesT", SleepMetricsWithBaselines, RecoveryMetricsWithBaselines)


class BaselineCalculator:
    """
    Calculate personal baselines for Garmin metrics.

    This class handles the calculation of baselines (mean, standard deviation) for
    various health metrics based on historical data, and compares current metrics
    against these baselines to provide contextual insights.
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        sleep_calculator: Optional[SleepMetricsCalculator] = None,
        recovery_calculator: Optional[RecoveryMetricsCalculator] = None,
    ):
        """
        Initialize the baseline calculator.

        Args:
            conn: DuckDB connection for accessing stored Garmin data
            sleep_calculator: Optional SleepMetricsCalculator instance
            recovery_calculator: Optional RecoveryMetricsCalculator instance
        """
        self.conn = conn

        # Ensure JSON extension is loaded
        try:
            self.conn.execute("LOAD json")
        except Exception as e:
            logger.warning(f"Failed to load JSON extension: {e}")

        self.sleep_calculator = sleep_calculator or SleepMetricsCalculator(conn)
        self.recovery_calculator = recovery_calculator or RecoveryMetricsCalculator(conn)

        # Default lookback periods for different metrics
        self.default_lookback_days = {
            "sleep": 30,  # 30 days for sleep metrics
            "recovery": 30,  # 30 days for recovery metrics
            "hrv": 90,  # 90 days for HRV (needs longer period)
            "rhr": 60,  # 60 days for resting heart rate
        }

    async def calculate_sleep_baselines(
        self,
        user_id: int,
        date: Union[dt.date, str],
        lookback_days: Optional[int] = None,
        ensure_data_available_func=None,
    ) -> dict[str, BaselineData]:
        """
        Calculate baseline values for sleep metrics.

        Args:
            user_id: User ID
            date: Reference date (baselines will include data up to this date)
            lookback_days: Number of days to look back for baseline calculation
            ensure_data_available_func: Optional function to ensure data is available

        Returns:
            Dictionary mapping metric names to BaselineData objects
        """
        # Convert string date to date object if needed
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)

        # Use default lookback period if not specified
        lookback_days = lookback_days or self.default_lookback_days["sleep"]

        # Define the start date for baseline calculation
        start_date = date - dt.timedelta(days=lookback_days)

        # Get historical sleep metrics
        sleep_metrics_history = await self.sleep_calculator.calculate_sleep_metrics_range(
            user_id, start_date, date, ensure_data_available_func
        )

        # If we don't have enough data, return empty dict
        if len(sleep_metrics_history) < 7:  # Require at least 7 days of data
            logger.warning(f"Not enough sleep data for user {user_id} to calculate baselines")
            return {}

        # Convert metrics to list for DuckDB processing
        sleep_data = []
        for d, metrics in sleep_metrics_history.items():
            if not metrics or not metrics.total_sleep_seconds:
                continue

            sleep_data.append(
                {
                    "date": d.isoformat(),
                    "total_sleep_seconds": metrics.total_sleep_seconds,
                    "deep_sleep_seconds": metrics.deep_sleep_seconds,
                    "light_sleep_seconds": metrics.light_sleep_seconds,
                    "rem_sleep_seconds": metrics.rem_sleep_seconds,
                    "awake_seconds": metrics.awake_seconds,
                    "sleep_efficiency_pct": metrics.sleep_efficiency_pct,
                    "waso_seconds": metrics.waso_seconds,
                    "deep_sleep_pct": metrics.deep_sleep_pct,
                    "light_sleep_pct": metrics.light_sleep_pct,
                    "rem_sleep_pct": metrics.rem_sleep_pct,
                    "avg_sleep_stress": metrics.avg_sleep_stress,
                }
            )

        if not sleep_data:
            logger.warning(f"No valid sleep data for user {user_id} to calculate baselines")
            return {}

        # Calculate metrics using Python instead of DuckDB JSON functions
        sleep_metrics_columns = [
            "total_sleep_seconds",
            "sleep_efficiency_pct",
            "waso_seconds",
            "deep_sleep_pct",
            "light_sleep_pct",
            "rem_sleep_pct",
            "avg_sleep_stress",
        ]

        baselines = {}

        # Process data in Python
        for metric in sleep_metrics_columns:
            # Collect all values for this metric
            values = []
            for data_point in sleep_data:
                if data_point[metric] is not None:
                    values.append(data_point[metric])

            # Calculate statistics if we have enough data
            if len(values) >= 7:  # At least 7 days of data
                # Calculate mean
                mean = sum(values) / len(values)

                # Calculate standard deviation
                variance = sum((x - mean) ** 2 for x in values) / len(values)
                std_dev = math.sqrt(variance)

                if mean is not None and std_dev is not None and std_dev > 0:
                    baselines[metric] = BaselineData(mean=mean, std_dev=std_dev, lookback_days=lookback_days)

        return baselines

    async def calculate_recovery_baselines(
        self,
        user_id: int,
        date: Union[dt.date, str],
        lookback_days: Optional[int] = None,
        ensure_data_available_func=None,
    ) -> dict[str, BaselineData]:
        """
        Calculate baseline values for recovery metrics.

        Args:
            user_id: User ID
            date: Reference date (baselines will include data up to this date)
            lookback_days: Number of days to look back for baseline calculation
            ensure_data_available_func: Optional function to ensure data is available

        Returns:
            Dictionary mapping metric names to BaselineData objects
        """
        # Convert string date to date object if needed
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)

        # Use default lookback period if not specified
        lookback_days = lookback_days or self.default_lookback_days["recovery"]

        # Define the start date for baseline calculation
        start_date = date - dt.timedelta(days=lookback_days)

        # Get historical recovery metrics
        recovery_metrics_history = await self.recovery_calculator.calculate_recovery_metrics_range(
            user_id, start_date, date, ensure_data_available_func
        )

        # If we don't have enough data, return empty dict
        if len(recovery_metrics_history) < 7:  # Require at least 7 days of data
            logger.warning(f"Not enough recovery data for user {user_id} to calculate baselines")
            return {}

        # Convert metrics to list for DuckDB processing
        recovery_data = []
        for d, metrics in recovery_metrics_history.items():
            if not metrics:
                continue

            recovery_data.append(
                {
                    "date": d.isoformat(),
                    "resting_heart_rate": metrics.resting_heart_rate,
                    "hrv_rmssd": metrics.hrv_rmssd,
                    "hrv_7day_avg": metrics.hrv_7day_avg,
                    "body_battery_max": metrics.body_battery_max,
                    "body_battery_min": metrics.body_battery_min,
                    "body_battery_charged": metrics.body_battery_charged,
                    "body_battery_drained": metrics.body_battery_drained,
                    "avg_stress_level": metrics.avg_stress_level,
                }
            )

        if not recovery_data:
            logger.warning(f"No valid recovery data for user {user_id} to calculate baselines")
            return {}

        # Calculate metrics using Python instead of DuckDB JSON functions
        recovery_metrics_columns = [
            "resting_heart_rate",
            "hrv_rmssd",
            "body_battery_max",
            "body_battery_charged",
            "avg_stress_level",
        ]

        baselines = {}

        # Process data in Python
        for metric in recovery_metrics_columns:
            # Use specific lookback for certain metrics
            specific_lookback = (
                self.default_lookback_days["hrv"]
                if metric == "hrv_rmssd"
                else self.default_lookback_days["rhr"]
                if metric == "resting_heart_rate"
                else lookback_days
            )

            # Collect all values for this metric
            values = []
            for data_point in recovery_data:
                if data_point[metric] is not None:
                    values.append(data_point[metric])

            # Calculate statistics if we have enough data
            if len(values) >= 7:  # At least 7 days of data
                # Calculate mean
                mean = sum(values) / len(values)

                # Calculate standard deviation
                variance = sum((x - mean) ** 2 for x in values) / len(values)
                std_dev = math.sqrt(variance)

                if mean is not None and std_dev is not None and std_dev > 0:
                    baselines[metric] = BaselineData(mean=mean, std_dev=std_dev, lookback_days=specific_lookback)

        return baselines

    def calculate_metric_status(
        self, current_value: float, baseline: BaselineData, lower_is_better: bool = False
    ) -> tuple[float, BaselineStatus]:
        """
        Calculate z-score and status for a metric compared to its baseline.

        Args:
            current_value: The current value of the metric
            baseline: The baseline data for the metric
            lower_is_better: Whether lower values are better for this metric

        Returns:
            Tuple of (z-score, status)
        """
        # Calculate z-score
        z_score = (current_value - baseline.mean) / baseline.std_dev

        # Determine status based on z-score and whether lower or higher is better
        if lower_is_better:
            # For metrics where lower is better (e.g., stress, RHR)
            if z_score <= BaselineThresholds.LOWER_IS_BETTER_OPTIMAL:
                status = BaselineStatus.OPTIMAL
            elif z_score <= BaselineThresholds.NORMAL_UPPER:
                status = BaselineStatus.NORMAL
            elif z_score <= BaselineThresholds.SLIGHT_DEVIATION_UPPER:
                status = BaselineStatus.SLIGHT_DEVIATION
            else:
                status = BaselineStatus.CONCERNING
        else:
            # For metrics where higher is better (e.g., HRV, deep sleep %)
            if z_score >= BaselineThresholds.HIGHER_IS_BETTER_OPTIMAL:
                status = BaselineStatus.OPTIMAL
            elif z_score >= BaselineThresholds.NORMAL_LOWER:
                status = BaselineStatus.NORMAL
            elif z_score >= BaselineThresholds.SLIGHT_DEVIATION_LOWER:
                status = BaselineStatus.SLIGHT_DEVIATION
            else:
                status = BaselineStatus.CONCERNING

        return z_score, status

    def create_metric_with_baseline(
        self, current_value: float, baseline: Optional[BaselineData], lower_is_better: bool = False
    ) -> MetricWithBaseline:
        """
        Create a MetricWithBaseline object from a current value and baseline.

        Args:
            current_value: The current value of the metric
            baseline: The baseline data for the metric, or None if no baseline exists
            lower_is_better: Whether lower values are better for this metric

        Returns:
            MetricWithBaseline object
        """
        if not baseline or current_value is None:
            return MetricWithBaseline(
                value=current_value if current_value is not None else 0.0, status=BaselineStatus.NO_BASELINE
            )

        z_score, status = self.calculate_metric_status(current_value, baseline, lower_is_better)

        return MetricWithBaseline(
            value=current_value,
            baseline_mean=baseline.mean,
            baseline_std_dev=baseline.std_dev,
            z_score=z_score,
            status=status,
        )

    async def calculate_sleep_metrics_with_baselines(
        self,
        user_id: int,
        date: Union[dt.date, str],
        lookback_days: Optional[int] = None,
        ensure_data_available_func=None,
        baselines: Optional[dict[str, BaselineData]] = None,
    ) -> Optional[SleepMetricsWithBaselines]:
        """
        Calculate sleep metrics with baselines for context.

        Args:
            user_id: User ID
            date: Date to calculate metrics for
            lookback_days: Number of days to look back for baseline calculation
            ensure_data_available_func: Optional function to ensure data is available
            baselines: Optional pre-calculated baselines to use

        Returns:
            SleepMetricsWithBaselines object or None if no data is available
        """
        # Convert string date to date object if needed
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)

        # Get current sleep metrics
        sleep_metrics = await self.sleep_calculator.calculate_sleep_metrics(user_id, date, ensure_data_available_func)

        if not sleep_metrics:
            logger.warning(f"No sleep metrics available for user {user_id} on {date}")
            return None

        # Calculate or use provided baselines
        if not baselines:
            baselines = await self.calculate_sleep_baselines(user_id, date, lookback_days, ensure_data_available_func)

        # Convert sleep metrics to metrics with baselines
        return SleepMetricsWithBaselines(
            date=date,
            total_sleep_time=self.create_metric_with_baseline(
                sleep_metrics.total_sleep_seconds,
                baselines.get("total_sleep_seconds"),
                lower_is_better=False,  # Higher sleep time is better
            ),
            sleep_efficiency=self.create_metric_with_baseline(
                sleep_metrics.sleep_efficiency_pct,
                baselines.get("sleep_efficiency_pct"),
                lower_is_better=False,  # Higher efficiency is better
            ),
            waso=(
                self.create_metric_with_baseline(
                    sleep_metrics.waso_seconds,
                    baselines.get("waso_seconds"),
                    lower_is_better=True,  # Lower WASO is better
                )
                if sleep_metrics.waso_seconds is not None
                else None
            ),
            deep_sleep_pct=(
                self.create_metric_with_baseline(
                    sleep_metrics.deep_sleep_pct,
                    baselines.get("deep_sleep_pct"),
                    lower_is_better=False,  # More deep sleep is better
                )
                if sleep_metrics.deep_sleep_pct is not None
                else None
            ),
            rem_sleep_pct=(
                self.create_metric_with_baseline(
                    sleep_metrics.rem_sleep_pct,
                    baselines.get("rem_sleep_pct"),
                    lower_is_better=False,  # More REM sleep is better
                )
                if sleep_metrics.rem_sleep_pct is not None
                else None
            ),
            avg_sleep_stress=(
                self.create_metric_with_baseline(
                    sleep_metrics.avg_sleep_stress,
                    baselines.get("avg_sleep_stress"),
                    lower_is_better=True,  # Lower sleep stress is better
                )
                if sleep_metrics.avg_sleep_stress is not None
                else None
            ),
        )

    async def calculate_recovery_metrics_with_baselines(
        self,
        user_id: int,
        date: Union[dt.date, str],
        lookback_days: Optional[int] = None,
        ensure_data_available_func=None,
        baselines: Optional[dict[str, BaselineData]] = None,
    ) -> Optional[RecoveryMetricsWithBaselines]:
        """
        Calculate recovery metrics with baselines for context.

        Args:
            user_id: User ID
            date: Date to calculate metrics for
            lookback_days: Number of days to look back for baseline calculation
            ensure_data_available_func: Optional function to ensure data is available
            baselines: Optional pre-calculated baselines to use

        Returns:
            RecoveryMetricsWithBaselines object or None if no data is available
        """
        # Convert string date to date object if needed
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)

        # Get current recovery metrics
        recovery_metrics = await self.recovery_calculator.calculate_recovery_metrics(
            user_id, date, ensure_data_available_func
        )

        if not recovery_metrics:
            logger.warning(f"No recovery metrics available for user {user_id} on {date}")
            return None

        # Calculate or use provided baselines
        if not baselines:
            baselines = await self.calculate_recovery_baselines(
                user_id, date, lookback_days, ensure_data_available_func
            )

        # Convert recovery metrics to metrics with baselines
        return RecoveryMetricsWithBaselines(
            date=date,
            resting_heart_rate=(
                self.create_metric_with_baseline(
                    recovery_metrics.resting_heart_rate,
                    baselines.get("resting_heart_rate"),
                    lower_is_better=True,  # Lower RHR is better
                )
                if recovery_metrics.resting_heart_rate is not None
                else MetricWithBaseline(value=0.0, status=BaselineStatus.NO_BASELINE)
            ),
            hrv_rmssd=(
                self.create_metric_with_baseline(
                    recovery_metrics.hrv_rmssd,
                    baselines.get("hrv_rmssd"),
                    lower_is_better=False,  # Higher HRV is better
                )
                if recovery_metrics.hrv_rmssd is not None
                else None
            ),
            body_battery_max=(
                self.create_metric_with_baseline(
                    recovery_metrics.body_battery_max,
                    baselines.get("body_battery_max"),
                    lower_is_better=False,  # Higher max body battery is better
                )
                if recovery_metrics.body_battery_max is not None
                else None
            ),
            body_battery_charged=(
                self.create_metric_with_baseline(
                    recovery_metrics.body_battery_charged,
                    baselines.get("body_battery_charged"),
                    lower_is_better=False,  # Higher body battery charge is better
                )
                if recovery_metrics.body_battery_charged is not None
                else None
            ),
            avg_stress_level=(
                self.create_metric_with_baseline(
                    recovery_metrics.avg_stress_level,
                    baselines.get("avg_stress_level"),
                    lower_is_better=True,  # Lower stress is better
                )
                if recovery_metrics.avg_stress_level is not None
                else None
            ),
        )

    async def calculate_baselines_for_date_range(
        self,
        user_id: int,
        start_date: Union[dt.date, str],
        end_date: Union[dt.date, str],
        lookback_days: Optional[int] = None,
        ensure_data_available_func=None,
        metrics_type: str = "both",
    ) -> dict[str, dict[dt.date, dict[str, BaselineData]]]:
        """
        Calculate baselines for a range of dates.

        Args:
            user_id: User ID
            start_date: Start date for baseline calculation
            end_date: End date for baseline calculation
            lookback_days: Number of days to look back for each baseline calculation
            ensure_data_available_func: Optional function to ensure data is available
            metrics_type: Type of metrics to calculate baselines for ('sleep', 'recovery', 'both')

        Returns:
            Dictionary with dates as keys and baseline dictionaries as values
        """
        # Convert string dates to date objects if needed
        if isinstance(start_date, str):
            start_date = dt.date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = dt.date.fromisoformat(end_date)

        result = {"sleep": {}, "recovery": {}}

        # Determine which metrics to calculate baselines for
        calc_sleep = metrics_type in ("sleep", "both")
        calc_recovery = metrics_type in ("recovery", "both")

        # Calculate baselines for each date in the range
        current_date = start_date
        while current_date <= end_date:
            if calc_sleep:
                sleep_baselines = await self.calculate_sleep_baselines(
                    user_id, current_date, lookback_days, ensure_data_available_func
                )
                result["sleep"][current_date] = sleep_baselines

            if calc_recovery:
                recovery_baselines = await self.calculate_recovery_baselines(
                    user_id, current_date, lookback_days, ensure_data_available_func
                )
                result["recovery"][current_date] = recovery_baselines

            current_date += dt.timedelta(days=1)

        return result

    def save_baselines_to_file(
        self, baselines: dict[str, dict[dt.date, dict[str, BaselineData]]], file_path: Union[str, Path]
    ) -> bool:
        """
        Save calculated baselines to a JSON file for later use.

        Args:
            baselines: Baselines dictionary to save
            file_path: Path to save the JSON file

        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert to a JSON-serializable format
            serializable_baselines = {}

            for metric_type, date_dict in baselines.items():
                serializable_baselines[metric_type] = {}

                for date, metrics_dict in date_dict.items():
                    date_str = date.isoformat()
                    serializable_baselines[metric_type][date_str] = {}

                    for metric_name, baseline_data in metrics_dict.items():
                        serializable_baselines[metric_type][date_str][metric_name] = {
                            "mean": baseline_data.mean,
                            "std_dev": baseline_data.std_dev,
                            "lookback_days": baseline_data.lookback_days,
                        }

            # Write to file
            with open(file_path, "w") as f:
                json.dump(serializable_baselines, f, indent=2)

            return True

        except Exception as e:
            logger.error(f"Error saving baselines to file: {e}")
            return False

    def load_baselines_from_file(
        self, file_path: Union[str, Path]
    ) -> dict[str, dict[dt.date, dict[str, BaselineData]]]:
        """
        Load previously calculated baselines from a JSON file.

        Args:
            file_path: Path to the JSON file containing baselines

        Returns:
            Dictionary of baselines
        """
        try:
            with open(file_path, "r") as f:
                loaded_data = json.load(f)

            # Convert back to proper types
            baselines = {}

            for metric_type, date_dict in loaded_data.items():
                baselines[metric_type] = {}

                for date_str, metrics_dict in date_dict.items():
                    date_obj = dt.date.fromisoformat(date_str)
                    baselines[metric_type][date_obj] = {}

                    for metric_name, baseline_dict in metrics_dict.items():
                        baselines[metric_type][date_obj][metric_name] = BaselineData(
                            mean=baseline_dict["mean"],
                            std_dev=baseline_dict["std_dev"],
                            lookback_days=baseline_dict["lookback_days"],
                        )

            return baselines

        except Exception as e:
            logger.error(f"Error loading baselines from file: {e}")
            return {"sleep": {}, "recovery": {}}
