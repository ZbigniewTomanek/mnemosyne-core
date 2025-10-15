#!/usr/bin/env python3
"""
Fetch raw data directly from all Garmin Connect endpoints for a specific date range and save as JSON files.

This script makes direct API calls to Garmin Connect and saves the raw JSON responses without processing,
allowing for inspection of the original data structure for debugging and development purposes.
"""

import argparse
import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import List, Optional

from loguru import logger

from telegram_bot.service.garmin_account_manager import GarminAccountManager


class DateEncoder(json.JSONEncoder):
    """JSON encoder that can handle date objects."""

    def default(self, obj):
        if isinstance(obj, dt.date):
            return obj.isoformat()
        return super().default(obj)


def daterange(start_date: Optional[dt.date] = None, end_date: Optional[dt.date] = None, days: int = 7) -> List[dt.date]:
    """
    Return a list of date objects between start_date and end_date.

    Args:
        start_date: The start date (optional).
        end_date: The end date (optional).
        days: Number of days to include (default: 7).

    Returns:
        List of date objects.
    """
    today = dt.datetime.now().date()

    if start_date and end_date:
        # Return all dates from start_date to end_date (inclusive)
        delta = (end_date - start_date).days
        return [start_date + dt.timedelta(days=i) for i in range(delta + 1)]
    elif start_date:
        # Return 'days' days starting from start_date
        return [start_date + dt.timedelta(days=i) for i in range(days)]
    elif end_date:
        # Return 'days' days ending on end_date
        return [end_date - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]
    else:
        # Return the last 'days' days ending today
        return [today - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]


async def fetch_and_save_garmin_data(
    telegram_user_id: int,
    token_store_dir: Path,
    output_dir: Path,
    date: Optional[str] = None,
    days: int = 1,
):
    """
    Fetch and save raw Garmin data for a specific date or date range.

    Args:
        telegram_user_id: The Telegram user ID to authenticate.
        token_store_dir: Directory where tokens are stored.
        output_dir: Directory to save output JSON files.
        date: Date to fetch data for (format: YYYY-MM-DD). If None, today's date is used.
        days: Number of days to fetch data for (default: 1).
    """
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize date if not provided
    if date is None:
        today = dt.datetime.now().date()
        date = today.isoformat()

    # Get date range
    start_date = dt.date.fromisoformat(date)
    end_date = start_date + dt.timedelta(days=days - 1)
    date_range = daterange(start_date, end_date, days)

    logger.info(f"Fetching data for dates: {date_range}")

    # Initialize the account manager
    account_manager = GarminAccountManager(token_store_dir)

    # Create client
    client = account_manager.create_client(telegram_user_id)
    if not client:
        logger.error(f"Could not create Garmin client for user {telegram_user_id}")
        return

    # Define all endpoints to fetch
    for single_date in date_range:
        date_str = single_date.isoformat()
        logger.info(f"Fetching data for date: {date_str}")

        # Fetch data from all endpoints and save them individually
        await fetch_daily_endpoints(client, single_date, output_dir)

    # Fetch additional endpoints that cover the entire date range
    await fetch_date_range_endpoints(client, start_date, end_date, output_dir)

    # Fetch user-specific endpoints that are not date-dependent
    await fetch_user_info_endpoints(client, output_dir, start_date)

    logger.info(f"All data fetched and saved to {output_dir}")


async def fetch_daily_endpoints(client, date: dt.date, output_dir: Path):
    """Fetch and save data from all daily endpoints."""
    date_str = date.isoformat()

    # Define all the daily endpoints to fetch
    endpoints = [
        # Core wellness endpoints
        ("steps", lambda: client.get_steps_data(date_str)),
        ("sleep", lambda: client.get_sleep_data(date_str)),
        ("hrv", lambda: client.get_hrv_data(date_str)),
        ("stress", lambda: client.get_stress_data(date_str)),
        ("respiration", lambda: client.get_respiration_data(date_str)),
        ("spo2", lambda: client.get_spo2_data(date_str)),
        ("resting_hr", lambda: client.get_rhr_day(date_str)),
        ("body_battery", lambda: client.get_body_battery_events(date_str)),
        ("heart_rates", lambda: client.get_heart_rates(date_str)),
        # Activity data
        ("activities", lambda: client.get_activities_fordate(date_str)),
        ("activities_detailed", lambda: client.get_activities_by_date(date_str, date_str)),
        # Additional wellness endpoints found in garmin_data_models.py
        ("floors", lambda: client.get_floors(date_str)),
        ("hydration", lambda: client.get_hydration_data(date_str)),
        ("intensity_minutes", lambda: client.get_intensity_minutes_data(date_str)),
    ]

    for name, fetch_fn in endpoints:
        try:
            logger.info(f"Fetching {name} for {date_str}")
            data = await fetch_with_retries(fetch_fn)

            # Save to file
            output_file = output_dir / f"garmin_{name}_{date_str}.json"
            with open(output_file, "w") as f:
                json.dump(data, f, cls=DateEncoder, indent=2)

            logger.info(f"Saved {name} for {date_str} to {output_file}")

            # For activities, also fetch detailed data for each activity
            if name == "activities" and isinstance(data, list):
                for activity in data:
                    activity_id = activity.get("activityId")
                    if activity_id:
                        await fetch_activity_details(client, activity_id, date_str, output_dir)

        except Exception as e:
            logger.error(f"Error fetching {name} for {date_str}: {str(e)}")
            # Save error information
            output_file = output_dir / f"garmin_{name}_{date_str}_error.json"
            with open(output_file, "w") as f:
                json.dump({"error": str(e), "date": date_str}, f, indent=2)


async def fetch_activity_details(client, activity_id: str, date_str: str, output_dir: Path):
    """Fetch and save detailed information for a specific activity."""
    # Define all activity-specific endpoints to fetch
    activity_endpoints = [
        ("activity_details", lambda: client.get_activity_details(activity_id)),
        ("activity_split_summaries", lambda: client.get_activity_split_summaries(activity_id)),
    ]

    for name, fetch_fn in activity_endpoints:
        try:
            logger.info(f"Fetching {name} for activity {activity_id}")
            data = await fetch_with_retries(fetch_fn)

            # Save to file
            output_file = output_dir / f"garmin_{name}_{activity_id}_{date_str}.json"
            with open(output_file, "w") as f:
                json.dump(data, f, cls=DateEncoder, indent=2)

            logger.info(f"Saved {name} for activity {activity_id} to {output_file}")
        except Exception as e:
            logger.error(f"Error fetching {name} for activity {activity_id}: {str(e)}")
            # Save error information
            output_file = output_dir / f"garmin_{name}_{activity_id}_{date_str}_error.json"
            with open(output_file, "w") as f:
                json.dump({"error": str(e), "activity_id": activity_id, "date": date_str}, f, indent=2)


async def fetch_date_range_endpoints(client, start_date: dt.date, end_date: dt.date, output_dir: Path):
    """Fetch and save data from endpoints that cover a date range."""
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    # Define endpoints that use date ranges
    endpoints = [
        # Using start_date for stats as it requires a date parameter
        ("stats", lambda: client.get_stats(start_str)),
        ("activities_between", lambda: client.get_activities_by_date(start_str, end_str)),
    ]

    # Try to fetch sleep data points if the method exists
    try:
        # Check if the method exists by calling dir() on the client
        client_methods = dir(client)
        if "get_sleep_data_points" in client_methods:
            endpoints.append(("sleep_data_points", lambda: client.get_sleep_data_points(start_str, end_str)))
    except Exception:
        logger.warning("get_sleep_data_points method not available on this Garmin client version")

    for name, fetch_fn in endpoints:
        try:
            logger.info(f"Fetching {name} for {start_str} to {end_str}")
            data = await fetch_with_retries(fetch_fn)

            # Save to file
            output_file = output_dir / f"garmin_{name}_{start_str}_to_{end_str}.json"
            with open(output_file, "w") as f:
                json.dump(data, f, cls=DateEncoder, indent=2)

            logger.info(f"Saved {name} to {output_file}")
        except Exception as e:
            logger.error(f"Error fetching {name} for {start_str} to {end_str}: {str(e)}")
            # Save error information
            output_file = output_dir / f"garmin_{name}_{start_str}_to_{end_str}_error.json"
            with open(output_file, "w") as f:
                json.dump({"error": str(e), "start_date": start_str, "end_date": end_str}, f, indent=2)


async def fetch_user_info_endpoints(client, output_dir: Path, reference_date: dt.date):
    """Fetch and save user-specific information that's not date-dependent."""
    # Get current timestamp for filename
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    date_str = reference_date.isoformat()

    # Define user-specific endpoints
    endpoints = [
        ("devices", lambda: client.get_devices()),
        ("personal_record", lambda: client.get_personal_record()),
        # fitness_age requires a date parameter
        ("fitness_age", lambda: client.get_fitnessage_data(date_str)),
    ]

    for name, fetch_fn in endpoints:
        try:
            logger.info(f"Fetching {name}")
            data = await fetch_with_retries(fetch_fn)

            # Save to file with timestamp
            output_file = output_dir / f"garmin_{name}_{timestamp}.json"
            with open(output_file, "w") as f:
                json.dump(data, f, cls=DateEncoder, indent=2)

            logger.info(f"Saved {name} to {output_file}")

            # For devices, also fetch solar data if available
            if name == "devices" and isinstance(data, list):
                for device in data:
                    device_id = device.get("deviceId")
                    if device_id:
                        try:
                            logger.info(f"Fetching solar data for device {device_id}")
                            # Solar data requires a date parameter
                            solar_data = await fetch_with_retries(
                                lambda: client.get_device_solar_data(device_id, date_str)
                            )
                            solar_file = output_dir / f"garmin_device_solar_{device_id}_{timestamp}.json"
                            with open(solar_file, "w") as f:
                                json.dump(solar_data, f, cls=DateEncoder, indent=2)
                            logger.info(f"Saved solar data for device {device_id} to {solar_file}")
                        except Exception as e:
                            logger.error(f"Error fetching solar data for device {device_id}: {str(e)}")
                            # Save error information
                            error_file = output_dir / f"garmin_device_solar_{device_id}_{timestamp}_error.json"
                            with open(error_file, "w") as f:
                                json.dump({"error": str(e), "device_id": device_id}, f, indent=2)
        except Exception as e:
            logger.error(f"Error fetching {name}: {str(e)}")
            # Save error information
            output_file = output_dir / f"garmin_{name}_{timestamp}_error.json"
            with open(output_file, "w") as f:
                json.dump({"error": str(e), "timestamp": timestamp}, f, indent=2)


async def fetch_consolidated_data(client, start_date: dt.date, end_date: dt.date, output_dir: Path):
    """Fetch and save a consolidated dataset with all metrics for the specified date range."""
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    try:
        logger.info(f"Collecting consolidated data for {start_str} to {end_str}")

        date_range = daterange(start_date, end_date)
        consolidated_data = []

        for date in date_range:
            date_str = date.isoformat()

            # Create a data structure for this day
            day_data = {"date": date_str}

            # Define all daily endpoints to fetch for consolidation
            endpoints = {
                "steps": client.get_steps_data,
                "sleep": client.get_sleep_data,
                "hrv": client.get_hrv_data,
                "stress": client.get_stress_data,
                "respiration": client.get_respiration_data,
                "spo2": client.get_spo2_data,
                "resting_hr": client.get_rhr_day,
                "body_battery": client.get_body_battery_events,
                "heart_rates": client.get_heart_rates,
                "activities": client.get_activities_fordate,
                "floors": client.get_floors,
                "hydration": client.get_hydration_data,
                "intensity_minutes": client.get_intensity_minutes_data,
            }

            # Fetch all endpoints for this day
            for name, fetch_fn in endpoints.items():
                try:
                    day_data[name] = await fetch_with_retries(lambda: fetch_fn(date_str))
                except Exception as e:
                    day_data[name] = {"error": str(e)}

            consolidated_data.append(day_data)
            logger.debug(f"Collected consolidated data for {date_str}")

        # Save the consolidated data
        output_file = output_dir / f"garmin_consolidated_{start_str}_to_{end_str}.json"
        with open(output_file, "w") as f:
            json.dump(consolidated_data, f, cls=DateEncoder, indent=2)

        logger.info(f"Saved consolidated data to {output_file}")
    except Exception as e:
        logger.error(f"Error collecting consolidated data: {str(e)}")
        output_file = output_dir / f"garmin_consolidated_{start_str}_to_{end_str}_error.json"
        with open(output_file, "w") as f:
            json.dump({"error": str(e), "start_date": start_str, "end_date": end_str}, f, indent=2)


async def fetch_with_retries(fetch_fn, max_retries: int = 3, backoff: int = 5):
    """Fetch data with retries and backoff for rate limiting."""
    for attempt in range(max_retries):
        try:
            return fetch_fn()
        except Exception as e:
            if "rate limit" in str(e).lower() or "too many requests" in str(e).lower():
                if attempt < max_retries - 1:
                    sleep_seconds = backoff * (attempt + 1)
                    logger.warning(f"Rate limit hit – retrying in {sleep_seconds}s…")
                    await asyncio.sleep(sleep_seconds)
                else:
                    raise
            else:
                raise


async def main():
    """Parse arguments and run the main function."""
    parser = argparse.ArgumentParser(description="Fetch raw Garmin Connect data and save as JSON files")
    parser.add_argument("--user_id", type=int, required=True, help="Telegram user ID")
    parser.add_argument("--token_dir", type=str, default="./tokens", help="Directory where tokens are stored")
    parser.add_argument("--output_dir", type=str, default="./garmin_data", help="Directory to save output JSON files")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to fetch data for (format: YYYY-MM-DD). If not provided, today's date is used.",
    )
    parser.add_argument("--days", type=int, default=1, help="Number of days to fetch data for (default: 1)")
    parser.add_argument(
        "--consolidated",
        action="store_true",
        help="Also generate a consolidated JSON file with all metrics for the specified date range",
    )

    args = parser.parse_args()

    token_store_dir = Path(args.token_dir)
    output_dir = Path(args.output_dir)

    await fetch_and_save_garmin_data(args.user_id, token_store_dir, output_dir, args.date, args.days)

    # If the consolidated flag is set, also generate a consolidated file
    if args.consolidated:
        # Initialize date if not provided
        if args.date is None:
            today = dt.datetime.now().date()
            start_date = today
        else:
            start_date = dt.date.fromisoformat(args.date)

        end_date = start_date + dt.timedelta(days=args.days - 1)

        # Create client for consolidated fetch
        account_manager = GarminAccountManager(token_store_dir)
        client = account_manager.create_client(args.user_id)
        if client:
            await fetch_consolidated_data(client, start_date, end_date, output_dir)
        else:
            logger.error("Could not create Garmin client for consolidated data")


if __name__ == "__main__":
    asyncio.run(main())
