"""
Sleep metrics analysis module.

This module provides functions for calculating sleep quality metrics from Garmin data.
"""

import datetime as dt
from pathlib import Path
from typing import Dict, Optional, Union

import duckdb
from loguru import logger

from telegram_bot.service.garmin_analysis.common.constants import DataTypes
from telegram_bot.service.garmin_analysis.common.data_models import SleepMetrics
from telegram_bot.service.garmin_analysis.common.db_utils import execute_query, load_sql_query


class SleepMetricsCalculator:
    """
    Calculate sleep quality metrics from Garmin data stored in DuckDB.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        """
        Initialize the sleep metrics calculator.

        Args:
            conn: DuckDB connection.
        """
        self.conn = conn
        self._load_queries()

    def _load_queries(self) -> None:
        """Load SQL queries from file."""
        queries_path = Path(__file__).parent / "queries" / "sleep_quality.sql"
        query_content = load_sql_query(queries_path)

        # Define the all metrics query directly to fix SQL issues
        self.all_metrics_query = """
        WITH sleep_data AS (
            SELECT
                json_data
            FROM garmin_raw_data
            WHERE user_id = ?
              AND date = ?
              AND data_type = 'sleep'
        ),
        sleep_metrics AS (
            SELECT
                CAST(json_extract_string(json_data, '$.dailySleepDTO.deepSleepSeconds') AS INTEGER) AS deep_sleep_seconds,
                CAST(json_extract_string(json_data, '$.dailySleepDTO.lightSleepSeconds') AS INTEGER) AS light_sleep_seconds,
                CAST(json_extract_string(json_data, '$.dailySleepDTO.remSleepSeconds') AS INTEGER) AS rem_sleep_seconds,
                CAST(json_extract_string(json_data, '$.dailySleepDTO.awakeSleepSeconds') AS INTEGER) AS awake_seconds,
                CAST(json_extract_string(json_data, '$.dailySleepDTO.sleepStartTimestampGMT') AS BIGINT) AS sleep_start_timestamp,
                CAST(json_extract_string(json_data, '$.dailySleepDTO.sleepEndTimestampGMT') AS BIGINT) AS sleep_end_timestamp,
                CAST(json_extract_string(json_data, '$.dailySleepDTO.restingHeartRateInBeatsPerMinute') AS INTEGER) AS resting_heart_rate,
                CAST(json_extract_string(json_data, '$.avgSleepStress') AS DOUBLE) AS avg_sleep_stress
            FROM sleep_data
        )
        SELECT
            (SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics) AS total_sleep_seconds,
            (SELECT deep_sleep_seconds FROM sleep_metrics) AS deep_sleep_seconds,
            (SELECT light_sleep_seconds FROM sleep_metrics) AS light_sleep_seconds,
            (SELECT rem_sleep_seconds FROM sleep_metrics) AS rem_sleep_seconds,
            (SELECT awake_seconds FROM sleep_metrics) AS awake_seconds,
            (SELECT resting_heart_rate FROM sleep_metrics) AS resting_heart_rate,
            (SELECT avg_sleep_stress FROM sleep_metrics) AS avg_sleep_stress,
            (SELECT sleep_start_timestamp FROM sleep_metrics) AS sleep_start_timestamp,
            (SELECT sleep_end_timestamp FROM sleep_metrics) AS sleep_end_timestamp,
            CASE
                WHEN (SELECT sleep_end_timestamp - sleep_start_timestamp FROM sleep_metrics) > 0 THEN
                    ((SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics) * 100.0) /
                    ((SELECT (sleep_end_timestamp - sleep_start_timestamp)/1000 FROM sleep_metrics))
                ELSE NULL
            END AS sleep_efficiency_pct,
            CASE
                WHEN (SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics) > 0 THEN
                    (SELECT deep_sleep_seconds FROM sleep_metrics) * 100.0 /
                    (SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics)
                ELSE NULL
            END AS deep_sleep_pct,
            CASE
                WHEN (SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics) > 0 THEN
                    (SELECT light_sleep_seconds FROM sleep_metrics) * 100.0 /
                    (SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics)
                ELSE NULL
            END AS light_sleep_pct,
            CASE
                WHEN (SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics) > 0 THEN
                    (SELECT rem_sleep_seconds FROM sleep_metrics) * 100.0 /
                    (SELECT deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds FROM sleep_metrics)
                ELSE NULL
            END AS rem_sleep_pct
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

    async def calculate_sleep_metrics(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[SleepMetrics]:
        """
        Calculate sleep metrics for a specific date.

        Args:
            user_id: User ID.
            date: Date to calculate metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            SleepMetrics object or None if no data is available.
        """
        # Convert string date to date object if needed
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)

        # Ensure we have the necessary data
        if ensure_data_available_func:
            data_available = await ensure_data_available_func(user_id, date, [DataTypes.SLEEP])
            if not data_available:
                logger.warning(f"No sleep data available for user {user_id} on {date}")
                return None

        try:
            # Execute the query to get all sleep metrics
            if not self.all_metrics_query:
                logger.error("All metrics query not found in SQL file")
                return None

            result = execute_query(self.conn, self.all_metrics_query, params=(user_id, date))

            if not result:
                logger.warning(f"No sleep data found for user {user_id} on {date}")
                return None

            # Create a SleepMetrics object from the result
            metrics_data = result[0]

            # Convert to model
            sleep_metrics = SleepMetrics(
                date=date,
                total_sleep_seconds=metrics_data.get("total_sleep_seconds"),
                deep_sleep_seconds=metrics_data.get("deep_sleep_seconds"),
                light_sleep_seconds=metrics_data.get("light_sleep_seconds"),
                rem_sleep_seconds=metrics_data.get("rem_sleep_seconds"),
                awake_seconds=metrics_data.get("awake_seconds"),
                sleep_efficiency_pct=metrics_data.get("sleep_efficiency_pct"),
                waso_seconds=metrics_data.get("awake_seconds"),  # Simplified WASO
                deep_sleep_pct=metrics_data.get("deep_sleep_pct"),
                light_sleep_pct=metrics_data.get("light_sleep_pct"),
                rem_sleep_pct=metrics_data.get("rem_sleep_pct"),
                avg_sleep_stress=metrics_data.get("avg_sleep_stress"),
                bedtime_timestamp=metrics_data.get("sleep_start_timestamp"),
                waketime_timestamp=metrics_data.get("sleep_end_timestamp"),
            )

            return sleep_metrics

        except Exception as e:
            logger.error(f"Error calculating sleep metrics for user {user_id} on {date}: {e}")
            return None

    async def calculate_sleep_metrics_range(
        self,
        user_id: int,
        start_date: Union[dt.date, str],
        end_date: Union[dt.date, str],
        ensure_data_available_func=None,
    ) -> Dict[dt.date, SleepMetrics]:
        """
        Calculate sleep metrics for a range of dates.

        Args:
            user_id: User ID.
            start_date: Start date of the range.
            end_date: End date of the range.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Dictionary of date -> SleepMetrics.
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
            metrics = await self.calculate_sleep_metrics(user_id, current_date, ensure_data_available_func)
            if metrics:
                result[current_date] = metrics
            current_date += dt.timedelta(days=1)

        return result

    async def get_total_sleep_time(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[int]:
        """
        Get total sleep time in seconds for a specific date.

        Args:
            user_id: User ID.
            date: Date to get metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Total sleep time in seconds or None if no data is available.
        """
        metrics = await self.calculate_sleep_metrics(user_id, date, ensure_data_available_func)
        return metrics.total_sleep_seconds if metrics else None

    async def get_sleep_efficiency(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[float]:
        """
        Get sleep efficiency for a specific date.

        Args:
            user_id: User ID.
            date: Date to get metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Sleep efficiency (%) or None if no data is available.
        """
        metrics = await self.calculate_sleep_metrics(user_id, date, ensure_data_available_func)
        return metrics.sleep_efficiency_pct if metrics else None

    async def get_sleep_stage_percentages(
        self, user_id: int, date: Union[dt.date, str], ensure_data_available_func=None
    ) -> Optional[Dict[str, float]]:
        """
        Get sleep stage percentages for a specific date.

        Args:
            user_id: User ID.
            date: Date to get metrics for.
            ensure_data_available_func: Optional function to ensure data is available.

        Returns:
            Dictionary of sleep stage percentages or None if no data is available.
        """
        metrics = await self.calculate_sleep_metrics(user_id, date, ensure_data_available_func)
        if not metrics:
            return None

        return {"deep": metrics.deep_sleep_pct, "light": metrics.light_sleep_pct, "rem": metrics.rem_sleep_pct}
