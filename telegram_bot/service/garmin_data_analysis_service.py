import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
from loguru import logger

from telegram_bot.service.garmin_connect_service import GarminConnectService
from telegram_bot.utils import get_user_directory


class GarminDataAnalysisService:
    """Service for analyzing Garmin Connect data using DuckDB.

    This service acts as a repository for Garmin Connect data. It stores raw JSON data in a DuckDB
    database and provides methods for querying and analyzing this data. If data for a requested date
    range is not available in the database, it automatically fetches it from the Garmin Connect API.
    """

    def __init__(self, garmin_service: GarminConnectService, out_dir: Path):
        """
        Initialize the Garmin data analysis service.

        Args:
            garmin_service: The GarminConnectService instance for fetching data.
            out_dir: Base output directory from config.
        """
        self.garmin_service = garmin_service
        self.out_dir = out_dir

        # Create a common directory for all garmin analysis data
        self.garmin_analysis_dir = self.out_dir / "garmin_analysis"
        self.garmin_analysis_dir.mkdir(parents=True, exist_ok=True)

        # Initialize DuckDB connection - this will be set per user in _setup_database
        self.conn = None
        self.current_user_id = None
        self.db_path = None

        logger.info(f"Initialized GarminDataAnalysisService with base storage at {self.garmin_analysis_dir}")

    def _setup_database(self, user_id: int = None):
        """
        Set up the DuckDB database and required tables for a specific user.

        Args:
            user_id: Telegram user ID. If None, uses the current user_id (must be set previously).
        """
        # If we have an active connection for a different user, close it first
        if self.conn and user_id and self.current_user_id != user_id:
            self.conn.close()
            self.conn = None

        # Set or validate the user_id
        if user_id:
            self.current_user_id = user_id
        elif not self.current_user_id:
            raise ValueError("No user_id provided and no current user set")

        # Get the user-specific directory
        user_data_dir = get_user_directory(self.out_dir, self.current_user_id, "garmin_analysis")

        # Create a connection to the DuckDB database file if not already connected
        if not self.conn:
            self.db_path = user_data_dir / "garmin_data.duckdb"
            self.conn = duckdb.connect(str(self.db_path))
            logger.info(f"Connected to database for user {self.current_user_id} at {self.db_path}")

        # Create tables if they don't exist
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS garmin_raw_data (
                user_id INTEGER,
                date DATE,
                data_type VARCHAR,
                json_data JSON,
                fetch_timestamp TIMESTAMP,
                PRIMARY KEY (user_id, date, data_type)
            )
        """
        )

        # Create a view for easier querying
        self.conn.execute(
            """
            CREATE OR REPLACE VIEW garmin_data_summary AS
            SELECT
                user_id,
                date,
                data_type,
                fetch_timestamp
            FROM garmin_raw_data
        """
        )

        # Load JSON extension if needed (usually auto-loaded)
        self.conn.execute("LOAD json")

    async def fetch_and_store_period_data(
        self,
        telegram_user_id: int,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        days: int = 7,
        force_refresh: bool = False,
    ) -> int:
        """
        Fetch data for a period and store it in the DuckDB database.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date for data retrieval.
            end_date: End date for data retrieval.
            days: Number of days if start/end dates not provided.
            force_refresh: If True, fetches data from the API even if it exists in the database.

        Returns:
            Number of days for which data was stored.
        """
        # Ensure database is set up for this user
        self._setup_database(telegram_user_id)

        # Calculate actual date range if not provided
        if not end_date:
            end_date = dt.date.today()

        if not start_date:
            start_date = end_date - dt.timedelta(days=days - 1)

        logger.info(f"Fetching and storing data for user {telegram_user_id} from {start_date} to {end_date}")

        # If not forcing a refresh, check what dates we already have in the database
        missing_dates = []
        if not force_refresh:
            date_range = [start_date + dt.timedelta(days=i) for i in range((end_date - start_date).days + 1)]
            existing_dates = self._get_dates_with_data(telegram_user_id, start_date, end_date)
            missing_dates = [date for date in date_range if date not in existing_dates]

            if not missing_dates:
                logger.info(f"All data for the period {start_date} to {end_date} already exists in the database")
                return 0

            logger.info(f"Need to fetch data for {len(missing_dates)} missing dates")
        else:
            # If forcing refresh, fetch all dates in range
            missing_dates = [start_date + dt.timedelta(days=i) for i in range((end_date - start_date).days + 1)]

        # Group consecutive dates to minimize API calls
        date_ranges = self._group_consecutive_dates(missing_dates)
        total_days_stored = 0

        # Fetch data for each range of missing dates
        for range_start, range_end in date_ranges:
            logger.info(f"Fetching data for range {range_start} to {range_end}")
            # Fetch raw data using the GarminConnectService
            raw_data = await self.garmin_service.export_raw_json(
                telegram_user_id=telegram_user_id, start_date=range_start, end_date=range_end
            )

            if not raw_data:
                logger.warning(f"No data returned for user {telegram_user_id} from {range_start} to {range_end}")
                continue

            # Current timestamp for recording when the data was fetched
            fetch_timestamp = dt.datetime.now()

            # Store the fetched data
            days_stored = self._store_raw_data(telegram_user_id, raw_data, fetch_timestamp)
            total_days_stored += days_stored
            logger.info(f"Stored data for {days_stored} days from range {range_start} to {range_end}")

        return total_days_stored

    def _store_raw_data(
        self, telegram_user_id: int, raw_data: List[Dict[str, Any]], fetch_timestamp: dt.datetime
    ) -> int:
        """
        Store raw data in the database.

        Args:
            telegram_user_id: The Telegram user ID.
            raw_data: List of daily data dictionaries.
            fetch_timestamp: When the data was fetched.

        Returns:
            Number of days for which data was stored.
        """
        # Process and store each day's data
        days_stored = 0
        for daily_data in raw_data:
            # Skip days with errors
            if "error" in daily_data:
                logger.warning(f"Skipping day with error: {daily_data.get('error')}")
                continue

            # Extract date from the data
            # The date could be in different formats depending on the data source
            date_str = None
            if "date" in daily_data:
                date_str = daily_data["date"]
            elif "calendarDate" in daily_data:
                date_str = daily_data["calendarDate"]
            elif "startTimeInSeconds" in daily_data:
                # Convert timestamp to date
                timestamp = daily_data["startTimeInSeconds"]
                date_str = dt.datetime.fromtimestamp(timestamp).date().isoformat()

            if not date_str:
                logger.warning(f"Could not determine date for data: {daily_data.keys()}")
                continue

            # Convert string date to date object if needed
            if isinstance(date_str, str):
                try:
                    date_obj = dt.date.fromisoformat(date_str)
                except ValueError:
                    logger.error(f"Invalid date format: {date_str}")
                    continue
            else:
                date_obj = date_str

            # Store different data types separately
            for data_type, data in self._extract_data_types(daily_data).items():
                try:
                    # Convert the data to a JSON string
                    json_data = json.dumps(data)

                    # Insert or replace data in the database
                    self.conn.execute(
                        """
                        INSERT OR REPLACE INTO garmin_raw_data
                        (user_id, date, data_type, json_data, fetch_timestamp)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (telegram_user_id, date_obj, data_type, json_data, fetch_timestamp),
                    )

                    logger.debug(f"Stored {data_type} data for user {telegram_user_id} on {date_obj}")
                except Exception as e:
                    logger.error(f"Error storing {data_type} data for {date_obj}: {str(e)}")

            days_stored += 1

        # Commit the changes
        self.conn.commit()
        logger.info(f"Successfully stored data for {days_stored} days for user {telegram_user_id}")

        return days_stored

    def _get_dates_with_data(self, telegram_user_id: int, start_date: dt.date, end_date: dt.date) -> List[dt.date]:
        """
        Get dates that already have data in the database within the specified range.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date of the range.
            end_date: End date of the range.

        Returns:
            List of dates that have data in the database.
        """
        try:
            result = self.conn.execute(
                """
                SELECT DISTINCT date
                FROM garmin_raw_data
                WHERE user_id = ?
                AND date BETWEEN ? AND ?
                ORDER BY date
                """,
                (telegram_user_id, start_date, end_date),
            ).fetchall()

            return [row[0] for row in result]
        except Exception as e:
            logger.error(f"Error getting dates with data: {str(e)}")
            return []

    def _group_consecutive_dates(self, dates: List[dt.date]) -> List[Tuple[dt.date, dt.date]]:
        """
        Group consecutive dates into ranges to optimize API calls.

        Args:
            dates: List of dates to group.

        Returns:
            List of (start_date, end_date) tuples representing consecutive date ranges.
        """
        if not dates:
            return []

        # Sort dates
        sorted_dates = sorted(dates)

        # Initialize result and current range
        ranges = []
        range_start = sorted_dates[0]
        range_end = range_start

        for i in range(1, len(sorted_dates)):
            # If the next date is consecutive, extend the range
            if sorted_dates[i] == range_end + dt.timedelta(days=1):
                range_end = sorted_dates[i]
            else:
                # Otherwise, close the current range and start a new one
                ranges.append((range_start, range_end))
                range_start = sorted_dates[i]
                range_end = range_start

        # Add the last range
        ranges.append((range_start, range_end))

        return ranges

    def _extract_data_types(self, daily_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract different data types from the daily data for storage.

        Args:
            daily_data: Raw daily data from Garmin Connect.

        Returns:
            Dictionary with data types as keys and the data as values.
        """
        data_types = {}

        # Map of known data types and their keys in the daily data
        type_keys = {
            "steps": "steps",
            "sleep": "sleep",
            "heart_rate": "heartRateValues",
            "resting_heart_rate": "restingHeartRate",
            "body_battery": "bodyBattery",
            "stress": "stress",
            "hrv": "hrv",
            "spo2": "spo2",
            "respiration": "respiration",
            "activities": "activities_detailed",
            "intensity_minutes": "intensity_minutes_detailed",
            "floors": "floors",
            "hydration": "hydration",
            "fitness_age": "fitness_age",
            "user_devices": "user_devices",
            "device_solar_data": "device_solar_data",
            "personal_records": "personal_records",
        }

        # Extract each data type if it exists
        for data_type, key in type_keys.items():
            if key in daily_data and daily_data[key] is not None:
                data_types[data_type] = daily_data[key]

        # If no specific types were found, store everything as "raw"
        if not data_types:
            data_types["raw"] = daily_data

        return data_types

    def get_available_data_periods(self, telegram_user_id: int) -> List[Dict[str, Any]]:
        """
        Get a list of date periods for which data is available.

        Args:
            telegram_user_id: The Telegram user ID.

        Returns:
            List of period dictionaries with start_date, end_date and data_types.
        """
        try:
            # Ensure database is set up for this user
            self._setup_database(telegram_user_id)

            # Query the database to get available date ranges and data types
            result = self.conn.execute(
                """
                WITH date_ranges AS (
                    SELECT
                        MIN(date) AS start_date,
                        MAX(date) AS end_date,
                        ARRAY_AGG(DISTINCT data_type) AS data_types,
                        COUNT(DISTINCT date) AS days_count
                    FROM garmin_raw_data
                    WHERE user_id = ?
                    GROUP BY DATE_TRUNC('month', date)
                    ORDER BY start_date DESC
                )
                SELECT
                    start_date,
                    end_date,
                    data_types,
                    days_count
                FROM date_ranges
            """,
                (telegram_user_id,),
            ).fetchall()

            # Format the results
            periods = []
            for row in result:
                periods.append({"start_date": row[0], "end_date": row[1], "data_types": row[2], "days_count": row[3]})

            logger.info(f"Found {len(periods)} data periods for user {telegram_user_id}")
            return periods

        except Exception as e:
            logger.error(f"Error getting available data periods: {str(e)}")
            return []

    async def query_data(
        self,
        telegram_user_id: int,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        data_types: Optional[List[str]] = None,
        auto_fetch: bool = True,
    ) -> Dict[str, Any]:
        """
        Query stored data for analysis. If data is missing and auto_fetch is True,
        it will be fetched from the Garmin Connect API.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date for querying.
            end_date: End date for querying.
            data_types: Specific data types to query.
            auto_fetch: If True, automatically fetch missing data from the API.

        Returns:
            Dictionary with query results.
        """
        try:
            # Ensure database is set up for this user
            self._setup_database(telegram_user_id)

            # Set default date range if not specified
            if not start_date:
                # Default to last 7 days if no start date is provided
                start_date = dt.date.today() - dt.timedelta(days=7)

            if not end_date:
                end_date = dt.date.today()

            # Check if we need to fetch data
            if auto_fetch:
                date_range = [start_date + dt.timedelta(days=i) for i in range((end_date - start_date).days + 1)]
                existing_dates = self._get_dates_with_data(telegram_user_id, start_date, end_date)
                missing_dates = [date for date in date_range if date not in existing_dates]

                if missing_dates:
                    logger.info(f"Fetching {len(missing_dates)} missing dates before querying data")
                    await self.fetch_and_store_period_data(
                        telegram_user_id=telegram_user_id, start_date=start_date, end_date=end_date, force_refresh=False
                    )

            # Build the data type filter
            data_type_filter = ""
            params = [telegram_user_id, start_date, end_date]

            if data_types:
                placeholders = ", ".join(["?"] * len(data_types))
                data_type_filter = f"AND data_type IN ({placeholders})"
                params.extend(data_types)

            # Query the database for the specified data
            result = self.conn.execute(
                f"""
                SELECT
                    date,
                    data_type,
                    json_data
                FROM garmin_raw_data
                WHERE user_id = ?
                AND date BETWEEN ? AND ?
                {data_type_filter}
                ORDER BY date, data_type
            """,
                params,
            ).fetchall()

            # Organize the results by date and data type
            organized_data = {}
            for row in result:
                date_str = row[0].isoformat()
                data_type = row[1]
                json_data = row[2]

                # Parse the JSON data from the string
                try:
                    parsed_data = json.loads(json_data)
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse JSON data for {date_str}, {data_type}")
                    continue

                # Initialize the date entry if it doesn't exist
                if date_str not in organized_data:
                    organized_data[date_str] = {}

                # Add the data to the organized data
                organized_data[date_str][data_type] = parsed_data

            # Structure the final result
            result = {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": (end_date - start_date).days + 1,
                },
                "data": organized_data,
                "data_types": list(set(row[1] for row in result)),
                "available_dates": list(organized_data.keys()),
            }

            logger.info(f"Retrieved data for user {telegram_user_id} from {start_date} to {end_date}")
            return result

        except Exception as e:
            logger.error(f"Error querying data: {str(e)}")
            return {
                "error": str(e),
                "period": {
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                },
            }

    async def get_data_summary(
        self,
        telegram_user_id: int,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        auto_fetch: bool = True,
    ) -> Dict[str, Any]:
        """
        Get a summary of the stored data for analysis.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date for querying.
            end_date: End date for querying.
            auto_fetch: If True, automatically fetch missing data from the API.

        Returns:
            Dictionary with summary statistics.
        """
        try:
            # Ensure database is set up for this user
            self._setup_database(telegram_user_id)

            # Set default date range if not specified
            if not start_date:
                # Default to last 7 days if no start date is provided
                start_date = dt.date.today() - dt.timedelta(days=7)

            if not end_date:
                end_date = dt.date.today()

            # Check if we need to fetch data
            if auto_fetch:
                date_range = [start_date + dt.timedelta(days=i) for i in range((end_date - start_date).days + 1)]
                existing_dates = self._get_dates_with_data(telegram_user_id, start_date, end_date)
                missing_dates = [date for date in date_range if date not in existing_dates]

                if missing_dates:
                    logger.info(f"Fetching {len(missing_dates)} missing dates before generating summary")
                    await self.fetch_and_store_period_data(
                        telegram_user_id=telegram_user_id, start_date=start_date, end_date=end_date, force_refresh=False
                    )

            # Query to get a summary of data
            summary = {}

            # Get data type counts
            type_counts = self.conn.execute(
                """
                SELECT
                    data_type,
                    COUNT(DISTINCT date) AS days_count
                FROM garmin_raw_data
                WHERE user_id = ?
                AND date BETWEEN ? AND ?
                GROUP BY data_type
                ORDER BY days_count DESC
            """,
                (telegram_user_id, start_date, end_date),
            ).fetchall()

            summary["data_type_coverage"] = {row[0]: row[1] for row in type_counts}

            # Get date coverage
            date_coverage = self.conn.execute(
                """
                SELECT
                    COUNT(DISTINCT date) AS days_with_data,
                    ? - ? + 1 AS total_days_in_range
                FROM garmin_raw_data
                WHERE user_id = ?
                AND date BETWEEN ? AND ?
            """,
                ((end_date - start_date).days + 1, 0, telegram_user_id, start_date, end_date),
            ).fetchone()

            if date_coverage:
                days_with_data = date_coverage[0]
                total_days = date_coverage[1]
                coverage_pct = (days_with_data / total_days * 100) if total_days > 0 else 0

                summary["date_coverage"] = {
                    "days_with_data": days_with_data,
                    "total_days": total_days,
                    "coverage_percentage": round(coverage_pct, 2),
                }

            # Get overview of data by aggregating key metrics if available
            # This is more advanced and will depend on the actual data structure
            # For now, we'll just return a placeholder for future implementation
            summary["metrics_overview"] = "Available in future implementation"

            logger.info(f"Generated data summary for user {telegram_user_id} from {start_date} to {end_date}")
            return summary

        except Exception as e:
            logger.error(f"Error generating data summary: {str(e)}")
            return {
                "error": str(e),
                "period": {
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                },
            }

    async def ensure_data_available(
        self,
        telegram_user_id: int,
        date: dt.date,
        data_types: Optional[List[str]] = None,
    ) -> bool:
        """
        Ensure that data for the specified date and data types is available in the database.
        If not, fetch it from the Garmin Connect API.

        Args:
            telegram_user_id: The Telegram user ID.
            date: The date for which to ensure data is available.
            data_types: Specific data types to check for and fetch if missing.

        Returns:
            True if the data is available (or was successfully fetched), False otherwise.
        """
        # Ensure database is set up for this user
        self._setup_database(telegram_user_id)

        # Check if the date has data in the database
        existing_dates = self._get_dates_with_data(telegram_user_id, date, date)

        if date in existing_dates:
            # If specific data types are requested, check if they exist
            if data_types:
                missing_types = self._get_missing_data_types(telegram_user_id, date, data_types)
                if missing_types:
                    logger.info(f"Date {date} exists but missing data types: {missing_types}")
                    # Need to fetch specific data types - force refresh for this date
                    days_stored = await self.fetch_and_store_period_data(
                        telegram_user_id=telegram_user_id, start_date=date, end_date=date, force_refresh=True
                    )
                    return days_stored > 0
            return True
        else:
            # Date doesn't exist, fetch it from the API
            logger.info(f"Fetching missing data for date {date}")
            days_stored = await self.fetch_and_store_period_data(
                telegram_user_id=telegram_user_id, start_date=date, end_date=date, force_refresh=False
            )
            return days_stored > 0

    def _get_missing_data_types(self, telegram_user_id: int, date: dt.date, required_types: List[str]) -> List[str]:
        """
        Get data types that are missing for the specified date.

        Args:
            telegram_user_id: The Telegram user ID.
            date: The date to check.
            required_types: List of data types that are required.

        Returns:
            List of data types that are missing.
        """
        try:
            result = self.conn.execute(
                """
                SELECT DISTINCT data_type
                FROM garmin_raw_data
                WHERE user_id = ?
                AND date = ?
                """,
                (telegram_user_id, date),
            ).fetchall()

            existing_types = [row[0] for row in result]
            return [data_type for data_type in required_types if data_type not in existing_types]
        except Exception as e:
            logger.error(f"Error getting existing data types: {str(e)}")
            return required_types

    def close(self):
        """Close the database connection."""
        if hasattr(self, "conn") and self.conn:
            self.conn.close()
