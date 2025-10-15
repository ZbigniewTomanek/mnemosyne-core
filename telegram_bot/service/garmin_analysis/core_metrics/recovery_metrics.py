"""
Recovery metrics analysis module.

This module provides functions for calculating recovery and ANS (Autonomic Nervous System)
metrics from Garmin data.
"""

import datetime as dt
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import duckdb
from loguru import logger

from telegram_bot.service.garmin_analysis.common.constants import DataTypes
from telegram_bot.service.garmin_analysis.common.data_models import RecoveryMetrics
from telegram_bot.service.garmin_analysis.common.db_utils import execute_query, load_sql_query


class RecoveryMetricsCalculator:
    """
    Calculate recovery and ANS metrics from Garmin data stored in DuckDB.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        """
        Initialize the recovery metrics calculator.

        Args:
            conn: DuckDB connection.
        """
        self.conn = conn
        self._load_queries()

    def _load_queries(self) -> None:
        """Load SQL queries from file."""
        queries_path = Path(__file__).parent / "queries" / "ans_status.sql"
        query_content = load_sql_query(queries_path)

        # Define the all metrics query directly to fix SQL issues
        self.all_metrics_query = r"""
        WITH sleep_data AS (
            SELECT
                CAST(json_extract_string(json_data, '$.dailySleepDTO.restingHeartRateInBeatsPerMinute') 
                AS INTEGER) AS sleep_rhr
            FROM garmin_raw_data
            WHERE user_id = ?
              AND date = ?
              AND data_type = 'sleep'
        ),
        rhr_data AS (
            SELECT
                CAST(json_extract_string(json_data, '$.restingHeartRate') AS INTEGER) AS direct_rhr
            FROM garmin_raw_data
            WHERE user_id = ?
              AND date = ?
              AND data_type = 'resting_heart_rate'
        ),
        hrv_data AS (
            SELECT
                CAST(json_extract_string(json_data, '$.hrvSummary.lastNightAvg') AS DOUBLE) AS nightly_hrv_rmssd
            FROM garmin_raw_data
            WHERE user_id = ?
              AND date = ?
              AND data_type = 'hrv'
        ),
        hrv_rolling AS (
            SELECT
                AVG(CAST(json_extract_string(json_data, '$.hrvSummary.lastNightAvg') AS DOUBLE)) AS hrv_7d_avg
            FROM garmin_raw_data
            WHERE user_id = ?
              AND data_type = 'hrv'
              AND json_extract_string(json_data, '$.hrvSummary.lastNightAvg') IS NOT NULL
              AND date BETWEEN (? - INTERVAL '6 days') AND ?
        ),
        stress_data AS (
            SELECT
                CAST(json_extract_string(json_data, '$.avgStressLevel') AS DOUBLE) AS avg_stress_level,
                CAST(json_extract_string(json_data, '$.maxStressLevel') AS DOUBLE) AS max_stress_level,
                json_data AS stress_json
            FROM garmin_raw_data
            WHERE user_id = ?
              AND date = ?
              AND data_type = 'stress'
        ),
        body_battery_data AS (
            SELECT
                json_data AS bb_json
            FROM garmin_raw_data
            WHERE user_id = ?
              AND date = ?
              AND data_type = 'body_battery'
        )
        SELECT
            -- Resting Heart Rate (take the lowest value available)
            COALESCE(
                (SELECT sleep_rhr FROM sleep_data),
                (SELECT direct_rhr FROM rhr_data)
            ) AS resting_heart_rate,

            -- HRV values
            (SELECT nightly_hrv_rmssd FROM hrv_data) AS hrv_rmssd,
            (SELECT hrv_7d_avg FROM hrv_rolling) AS hrv_7day_avg,

            -- Body Battery values from either source
            CASE
                WHEN json_extract_string((SELECT bb_json FROM body_battery_data), '$.bodyBatteryValueDescriptors.charged') ~ '^\d+$'
                THEN CAST(json_extract_string((SELECT bb_json FROM body_battery_data), '$.bodyBatteryValueDescriptors.charged') AS INTEGER)
                ELSE NULL
            END AS body_battery_charged,
            CASE
                WHEN json_extract_string((SELECT bb_json FROM body_battery_data), '$.bodyBatteryValueDescriptors.drained') ~ '^\d+$'
                THEN CAST(json_extract_string((SELECT bb_json FROM body_battery_data), '$.bodyBatteryValueDescriptors.drained') AS INTEGER)
                ELSE NULL
            END AS body_battery_drained,
            CASE
                WHEN json_extract_string((SELECT stress_json FROM stress_data), '$.bodyBatteryChange') ~ '^\d+$'
                THEN CAST(json_extract_string((SELECT stress_json FROM stress_data), '$.bodyBatteryChange') AS INTEGER)
                ELSE NULL
            END AS body_battery_max,
            CASE
                WHEN json_extract_string((SELECT bb_json FROM body_battery_data), '$.bodyBatteryValuesArray[0][2]') ~ '^\d+$'
                THEN CAST(json_extract_string((SELECT bb_json FROM body_battery_data), '$.bodyBatteryValuesArray[0][2]') AS INTEGER)
                ELSE NULL
            END AS body_battery_min,

            -- Stress
            (SELECT avg_stress_level FROM stress_data) AS avg_stress_level,
            (SELECT max_stress_level FROM stress_data) AS max_stress_level
        """

        # Extract other queries for individual metrics
        query_blocks = query_content.split("--")

        # Extract and store individual queries
        self.queries = {}
        current_name = None
        current_query = []

        for block in query_blocks:
            if not block.strip():
                continue

            lines = block.strip().split("\n")
            if len(lines) > 0 and lines[0].strip():
                # This is a header line with the query name
                if current_name and current_query:
                    self.queries[current_name] = "\n".join(current_query)

                current_name = lines[0].strip().lower().replace(" ", "_")
                current_query = []

                # Add remaining lines to the query
                for line in lines[1:]:
                    current_query.append(line)
            else:
                # Add all lines to the current query
                for line in lines:
                    current_query.append(line)

        # Add the last query
        if current_name and current_query:
            self.queries[current_name] = "\n".join(current_query)

    async def calculate_recovery_metrics(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[RecoveryMetrics]:
        """
        Calculate recovery metrics for a specific date.

        Args:
            user_id: User ID.
            date: Date to calculate metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            RecoveryMetrics object or None if no data is available.
        """
        # Convert string date to date object if needed
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)

        # Ensure we have the necessary data
        if ensure_data_available_func:
            required_data_types = [DataTypes.SLEEP, DataTypes.HRV, DataTypes.STRESS, DataTypes.BODY_BATTERY]
            data_available = await ensure_data_available_func(user_id, date, required_data_types)
            if not data_available:
                logger.warning(f"Some required recovery data not available for user {user_id} on {date}")
                # Continue anyway, we'll get partial data

        try:
            # Execute the query to get all recovery metrics
            if not self.all_metrics_query:
                logger.error("All recovery metrics query not found in SQL file")
                return None

            params = (
                user_id,
                date,  # sleep RHR params
                user_id,
                date,  # direct RHR params
                user_id,
                date,  # HRV params
                user_id,  # HRV rolling params (user)
                date - dt.timedelta(days=6),
                date,  # HRV rolling params (date range)
                user_id,
                date,  # stress params
                user_id,
                date,  # body battery params
            )

            result = execute_query(self.conn, self.all_metrics_query, params=params)

            if not result:
                logger.warning(f"No recovery data found for user {user_id} on {date}")
                return None

            # Create a RecoveryMetrics object from the result
            if not result:
                logger.warning(f"Query returned empty result for user {user_id} on {date}")
                return None

            metrics_data = result[0]

            # Check if we have any actual values (not just all None)
            has_values = any(value is not None for value in metrics_data.values())
            if not has_values:
                logger.warning(f"No recovery metric values found for user {user_id} on {date}")
                return None

            # Convert to model
            recovery_metrics = RecoveryMetrics(
                date=date,
                resting_heart_rate=metrics_data.get("resting_heart_rate"),
                hrv_rmssd=metrics_data.get("hrv_rmssd"),
                hrv_7day_avg=metrics_data.get("hrv_7day_avg"),
                body_battery_max=metrics_data.get("body_battery_max"),
                body_battery_min=metrics_data.get("body_battery_min"),
                body_battery_charged=metrics_data.get("body_battery_charged"),
                body_battery_drained=metrics_data.get("body_battery_drained"),
                avg_stress_level=metrics_data.get("avg_stress_level"),
            )

            return recovery_metrics

        except Exception as e:
            logger.error(f"Error calculating recovery metrics for user {user_id} on {date}: {e}")
            return None

    async def calculate_recovery_metrics_range(
        self,
        user_id: int,
        start_date: Union[dt.date, str],
        end_date: Union[dt.date, str],
        ensure_data_available_func=None,
    ) -> Dict[dt.date, RecoveryMetrics]:
        """
        Calculate recovery metrics for a range of dates.

        Args:
            user_id: User ID.
            start_date: Start date of the range.
            end_date: End date of the range.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Dictionary of date -> RecoveryMetrics.
        """
        # Convert string dates to date objects if needed
        if isinstance(start_date, str):
            start_date = dt.date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = dt.date.fromisoformat(end_date)

        # Calculate metrics for each date in the range
        result = {}
        current_date = start_date
        while current_date <= end_date:
            metrics = await self.calculate_recovery_metrics(user_id, current_date, ensure_data_available_func)
            if metrics:
                result[current_date] = metrics
            current_date += dt.timedelta(days=1)

        return result

    async def get_resting_heart_rate(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[int]:
        """
        Get resting heart rate for a specific date.

        Args:
            user_id: User ID.
            date: Date to get metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Resting heart rate (bpm) or None if no data is available.
        """
        metrics = await self.calculate_recovery_metrics(user_id, date, ensure_data_available_func)
        return metrics.resting_heart_rate if metrics else None

    async def get_hrv(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Get HRV and 7-day HRV average for a specific date.

        Args:
            user_id: User ID.
            date: Date to get metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Tuple of (HRV, 7-day HRV average) or (None, None) if no data is available.
        """
        metrics = await self.calculate_recovery_metrics(user_id, date, ensure_data_available_func)
        if not metrics:
            return None, None
        return metrics.hrv_rmssd, metrics.hrv_7day_avg

    async def get_body_battery(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[Dict[str, int]]:
        """
        Get Body Battery metrics for a specific date.

        Args:
            user_id: User ID.
            date: Date to get metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Dictionary of Body Battery metrics or None if no data is available.
        """
        metrics = await self.calculate_recovery_metrics(user_id, date, ensure_data_available_func)
        if not metrics:
            return None

        # Filter out None values
        bb_metrics = {
            "max": metrics.body_battery_max,
            "min": metrics.body_battery_min,
            "charged": metrics.body_battery_charged,
            "drained": metrics.body_battery_drained,
        }
        return {k: v for k, v in bb_metrics.items() if v is not None}

    async def get_stress_level(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[float]:
        """
        Get average stress level for a specific date.

        Args:
            user_id: User ID.
            date: Date to get metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Average stress level or None if no data is available.
        """
        metrics = await self.calculate_recovery_metrics(user_id, date, ensure_data_available_func)
        return metrics.avg_stress_level if metrics else None
