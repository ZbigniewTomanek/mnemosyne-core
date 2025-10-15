#!/usr/bin/env python3
"""
Data models and utility functions for Garmin Connect integration.

This module contains the data classes and helper functions used to retrieve,
process, and format Garmin Connect health and fitness data. It supports fetching
detailed activity data and all-day heart rate information to provide comprehensive
health and fitness insights.
"""

import datetime as dt
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Optional

import dateutil.tz
from garminconnect import Garmin, GarminConnectConnectionError, GarminConnectTooManyRequestsError
from loguru import logger


@dataclass
class DailyActivity:
    """
    Represents a single activity recorded in Garmin Connect.

    This class stores both summary information about an activity and the detailed
    data from the Garmin Connect API when available.
    """

    activity_type: str
    duration_seconds: float
    distance_meters: float
    avg_hr: float
    min_hr: Optional[float] = None
    max_hr: Optional[float] = None
    calories: int = 0
    moderate_intensity_minutes: int = 0
    vigorous_intensity_minutes: int = 0
    activity_id: Optional[int] = None  # Unique identifier for the activity
    details: Optional[dict[str, Any]] = None  # Complete detailed response from get_activity_details
    split_summaries: Optional[dict[str, Any]] = None  # Split data for the activity


@dataclass
class GarminDevice:
    """
    Represents a Garmin device registered to the user.
    """

    device_id: str
    device_name: str
    device_type: str
    mac_address: Optional[str] = None
    last_used: Optional[str] = None
    solar_data: Optional[dict[str, Any]] = None


@dataclass
class PersonalRecord:
    """
    Represents a personal record achieved by the user.
    """

    record_type: str
    value: float
    date: str
    activity_id: Optional[int] = None


@dataclass
class GarminDailyData:
    """
    Contains all health and fitness metrics for a single day.

    This class aggregates various health metrics from Garmin Connect including
    summary data and detailed activity information. It provides a comprehensive
    view of daily health and fitness data.
    """

    date: str
    # Steps data
    steps: int = 0
    floors_climbed: int = 0  # New field for floors data
    # Sleep data
    sleep_duration_hours: float = 0
    sleep_score: int = 0
    # HRV data
    hrv_last_night_avg: float = 0
    # Calories
    calories_burned: int = 0  # Total active calories for the day, preferably from AllDayHR
    # Intensity
    intensity_minutes: int = 0  # Sum of moderate and vigorous intensity minutes
    intensity_minutes_data: Optional[dict[str, Any]] = None  # Detailed intensity minutes data
    # Stress
    avg_stress_level: int = 0
    # Heart rate
    resting_hr: int = 0  # Daily resting heart rate, primarily from AllDayHR
    # Body battery
    body_battery_max: int = 0
    body_battery_min: int = 0
    # Blood oxygen
    avg_spo2: float = 0
    # Respiration
    avg_breath_rate: float = 0
    # Hydration
    hydration_amount_ml: float = 0  # New field for hydration data
    hydration_goal_ml: float = 0  # New field for hydration goal
    # Fitness age
    fitness_age: Optional[int] = None  # New field for fitness age
    fitness_age_data: Optional[dict[str, Any]] = None  # Additional fitness age insights
    # Devices
    devices: list[GarminDevice] = field(default_factory=list)  # User's Garmin devices
    # Personal records
    personal_records: list[PersonalRecord] = field(default_factory=list)  # User's personal records
    # Activities
    activities: list[DailyActivity] = field(default_factory=list)  # Individual activities with detailed data
    activities_detailed: Optional[dict[str, Any]] = None  # Comprehensive activities data


def daterange(start_date: Optional[dt.date] = None, end_date: Optional[dt.date] = None, days: int = 7) -> list[str]:
    """
    Return a list of date strings (YYYY-MM-DD) between start_date and end_date.

    If start_date is provided but end_date is not, return 'days' days starting from start_date.
    If end_date is provided but start_date is not, return 'days' days ending on end_date.
    If neither is provided, return the last 'days' days ending today.

    Args:
        start_date: The start date (optional).
        end_date: The end date (optional).
        days: Number of days to include (default: 7).

    Returns:
        List of date strings in YYYY-MM-DD format.
    """
    tz = dateutil.tz.tzlocal()
    today = dt.datetime.now(tz).date()

    if start_date and end_date:
        # Return all dates from start_date to end_date (inclusive)
        delta = (end_date - start_date).days
        return [(start_date + dt.timedelta(days=i)).isoformat() for i in range(delta + 1)]
    elif start_date:
        # Return 'days' days starting from start_date
        return [(start_date + dt.timedelta(days=i)).isoformat() for i in range(days)]
    elif end_date:
        # Return 'days' days ending on end_date
        return [(end_date - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    else:
        # Return the last 'days' days ending today
        return [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def get_daily_metrics(client: Garmin, date: str) -> dict[str, Any]:
    """
    Fetch all required metrics for a specific date and package into one dict.
    Includes detailed activity data and all-day heart rate data.

    Args:
        client: The Garmin client.
        date: Date string in YYYY-MM-DD format.

    Returns:
        Dictionary containing all metrics for the specified date, including
        detailed activity data and all-day heart rate data.
    """
    data: dict[str, Any] = {"date": date}

    api_map = {
        "steps": client.get_steps_data,
        "sleep": client.get_sleep_data,
        "hrv": client.get_hrv_data,
        "stress": client.get_stress_data,
        "respiration": client.get_respiration_data,
        "spo2": client.get_spo2_data,
        "resting_hr": client.get_rhr_day,
        "body_battery": client.get_body_battery_events,
        "activities": client.get_activities_fordate,
    }

    for key, fn in api_map.items():
        try:
            data[key] = fn(date)
        except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
            logger.warning(f"Error fetching {key} for {date}: {str(exc)}")
            data[key] = {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Unexpected error fetching {key} for {date}: {exc}")
            data[key] = {"error": str(exc)}

    # Fetch activity summaries
    try:
        # Try to get activities using the new API method first
        try:
            # Check if there's a new method or direct API call to fetch activities with details
            # For now, we'll use the existing method
            raw_activity_summaries = client.get_activities_fordate(date)

            # Process activity summaries normally
            process_activity_summaries(client, data, date, raw_activity_summaries)
        except Exception as e:
            logger.warning(f"Error with primary activity fetch for {date}: {str(e)}")
            # If that fails, try alternative approaches
            raw_activity_summaries = fetch_alternative_activity_data(client, date)

            if raw_activity_summaries:
                process_activity_summaries(client, data, date, raw_activity_summaries)
            else:
                # No data available
                data["ActivitiesForDay"] = {
                    "errorMessage": f"Failed to retrieve activities data: {str(e)}",
                    "headers": {},
                    "payload": [],
                    "requestUrl": "/activitylist-service/activities/fordailysummary",
                    "statusCode": 500,
                    "successful": False,
                }
    except Exception as exc:
        logger.error(f"Failed to fetch activities data for {date}: {str(exc)}")
        data["ActivitiesForDay"] = {
            "errorMessage": f"Failed to retrieve activities data: {str(exc)}",
            "headers": {},
            "payload": [],
            "requestUrl": "/activitylist-service/activities/fordailysummary",
            "statusCode": 500,
            "successful": False,
        }

    # Fetch all-day heart rate data
    try:
        all_day_hr_payload = client.get_heart_rates(date)
        # Store in the new flat structure
        data["AllDayHR"] = {
            "requestUrl": "/wellness-service/wellness/dailyHeartRate",
            "statusCode": 200,
            "headers": {},
            "errorMessage": None,
            "payload": all_day_hr_payload,
            "successful": True,
        }
    except Exception as exc:
        logger.warning(f"Error fetching all-day heart rate for {date}: {str(exc)}")
        all_day_hr_error = {
            "requestUrl": "/wellness-service/wellness/dailyHeartRate",
            "statusCode": 500,
            "headers": {},
            "errorMessage": str(exc),
            "payload": {},
            "successful": False,
        }

        data["AllDayHR"] = all_day_hr_error

    sleep_times_data = extract_sleep_times_from_data(data)
    if sleep_times_data:
        data["SleepTimes"] = sleep_times_data

    return data


def extract_sleep_times_from_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Extract sleep times from the sleep data.

    Args:
        data: The data dictionary containing sleep information.

    Returns:
        A dictionary with sleep times or empty dict if no data available.
    """
    # First, if SleepTimes is already available directly (like in the example data), use it
    if "SleepTimes" in data and isinstance(data["SleepTimes"], dict):
        return data["SleepTimes"]

    sleep_times = {}
    sleep_data = data.get("sleep", {})

    # Try to extract sleep times from sleep data
    try:
        daily_sleep_dto = sleep_data.get("dailySleepDTO", {})
        if daily_sleep_dto:
            # Current day sleep
            if "sleepStartTimeGMT" in daily_sleep_dto:
                sleep_times["currentDaySleepStartTimeGMT"] = int(daily_sleep_dto.get("sleepStartTimeGMT", 0))
            if "sleepEndTimeGMT" in daily_sleep_dto:
                sleep_times["currentDaySleepEndTimeGMT"] = int(daily_sleep_dto.get("sleepEndTimeGMT", 0))

        # Try to extract next day's sleep if available (from other sources)
        next_day_sleep = sleep_data.get("nextDaySleep", {})
        if next_day_sleep:
            if "sleepStartTimeGMT" in next_day_sleep:
                sleep_times["nextDaySleepStartTimeGMT"] = int(next_day_sleep.get("sleepStartTimeGMT", 0))
            if "sleepEndTimeGMT" in next_day_sleep:
                sleep_times["nextDaySleepEndTimeGMT"] = int(next_day_sleep.get("sleepEndTimeGMT", 0))
    except Exception as e:
        logger.warning(f"Error extracting sleep times: {e}")

    return sleep_times


def fetch_alternative_activity_data(client: Garmin, date: str) -> list[dict[str, Any]]:
    """
    Attempt to fetch activity data using alternative API methods.

    Args:
        client: The Garmin client.
        date: Date string in YYYY-MM-DD format.

    Returns:
        List of activity data or empty list if no data available.
    """
    try:
        # Try alternative method if available in the client
        # This is a placeholder for now
        return []
    except Exception:
        return []


def process_activity_summaries(client: Garmin, data: dict[str, Any], date: str, raw_activity_summaries: Any) -> None:
    """
    Process activity summaries and add them to the data dictionary.

    Args:
        client: The Garmin client.
        data: The data dictionary to add activity data to.
        date: Date string in YYYY-MM-DD format.
        raw_activity_summaries: Raw activity summaries from the Garmin API.
    """
    activity_summaries_response_successful = True
    activity_summaries_error_message = ""
    detailed_activities_payload = []

    # Handle different possible formats of the raw_activity_summaries
    if isinstance(raw_activity_summaries, dict) and "ActivitiesForDay" in raw_activity_summaries:
        # Format from the sample data - extract the payload
        activities_summary = raw_activity_summaries.get("ActivitiesForDay", {}).get("payload", [])
    elif isinstance(raw_activity_summaries, list):
        # Direct list format - use as is
        activities_summary = raw_activity_summaries
    else:
        # Try to extract a list from other possible formats
        if isinstance(raw_activity_summaries, dict):
            activities_summary = raw_activity_summaries.get("payload", [])
        else:
            # If we can't identify the format, log and use an empty list
            logger.warning(f"Unrecognized format for activity summaries on {date}: {type(raw_activity_summaries)}")
            activities_summary = []

    # Process the activity summaries
    if isinstance(activities_summary, list):
        for summary in activities_summary:
            if not isinstance(summary, dict):
                logger.warning(f"Activity summary is not a dictionary on {date}: {type(summary)}")
                continue

            activity_id = summary.get("activityId")
            if activity_id:
                try:
                    # Fetch detailed activity data
                    details = client.get_activity_details(str(activity_id))
                    detailed_activities_payload.append(details)
                except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
                    logger.warning(f"Error fetching details for activity {activity_id} on {date}: {str(exc)}")
                    summary_with_error = summary.copy()
                    summary_with_error["detailsFetchError"] = str(exc)
                    detailed_activities_payload.append(summary_with_error)
            else:
                logger.warning(f"Activity summary found without ID on {date}")
                detailed_activities_payload.append(summary)
    else:
        activity_summaries_response_successful = False
        activity_summaries_error_message = (
            f"Unexpected response format from get_activities_fordate: {type(activities_summary)}"
        )

    # Structure the activities data in both formats - old nested and new flat
    activities_data = {
        "requestUrl": "/activitylist-service/activities/fordailysummary",
        "statusCode": 200 if activity_summaries_response_successful else 500,
        "headers": {},
        "errorMessage": activity_summaries_error_message,
        "payload": detailed_activities_payload,
        "successful": activity_summaries_response_successful,
    }

    # Add to both formats for backward compatibility
    data["ActivitiesForDay"] = activities_data


def extract_daily_data(client: Garmin, date: str) -> GarminDailyData:  # noqa: C901
    """
    Extract Garmin Connect data for a specific date into a GarminDailyData object.
    Processes detailed activity data and all-day heart rate information.

    Args:
        client: The Garmin client.
        date: Date string in YYYY-MM-DD format.

    Returns:
        GarminDailyData object containing processed metrics for the specified date.
    """
    raw_data = get_daily_metrics(client, date)

    # Create a base daily data object with the date
    daily_data = GarminDailyData(date=date)

    # Helper function for safe data extraction
    def _safe_get(data_dict: dict, key_path: list[str], default: Any = 0):
        """Safely get a nested value from a dictionary."""
        try:
            temp_dict = data_dict
            for key in key_path:
                if temp_dict is None:
                    return default
                temp_dict = temp_dict.get(key)
            # Handle cases where the final value might be None
            return temp_dict if temp_dict is not None else default
        except (AttributeError, TypeError, IndexError):
            return default

    # Extract steps data
    daily_steps_list = _safe_get(raw_data, ["steps"], [])
    daily_data.steps = (
        sum(step_interval.get("steps", 0) for step_interval in daily_steps_list)
        if isinstance(daily_steps_list, list)
        else 0
    )

    # Extract floors data if available
    try:
        floors_data = client.get_floors(date)
        if isinstance(floors_data, list):
            daily_data.floors_climbed = sum(floor.get("value", 0) for floor in floors_data)
        elif isinstance(floors_data, dict):
            daily_data.floors_climbed = _safe_get(floors_data, ["floorsAscended"], 0)
    except Exception:
        daily_data.floors_climbed = 0

    # Extract hydration data if available
    try:
        hydration_data = client.get_hydration_data(date)
        if isinstance(hydration_data, dict):
            daily_data.hydration_amount_ml = _safe_get(hydration_data, ["valueInML"], 0)
            daily_data.hydration_goal_ml = _safe_get(hydration_data, ["goalInML"], 0)
    except Exception:
        daily_data.hydration_amount_ml = 0
        daily_data.hydration_goal_ml = 0

    # Extract fitness age data if available
    try:
        fitness_age_data = client.get_fitnessage_data()
        if isinstance(fitness_age_data, dict):
            daily_data.fitness_age = _safe_get(fitness_age_data, ["fitnessAge"], None)
            daily_data.fitness_age_data = fitness_age_data
    except Exception:
        daily_data.fitness_age = None
        daily_data.fitness_age_data = None

    # Try to get device information
    try:
        devices_data = client.get_devices()
        if devices_data and isinstance(devices_data, list):
            for device in devices_data:
                if isinstance(device, dict) and device.get("deviceId"):
                    device_id = device.get("deviceId")
                    device_obj = GarminDevice(
                        device_id=str(device_id),
                        device_name=device.get("productDisplayName", "Unknown Device"),
                        device_type=device.get("deviceType", "Unknown Type"),
                        mac_address=device.get("macAddress"),
                        last_used=device.get("lastUsedDate"),
                    )

                    # Try to get solar data if available
                    try:
                        solar_data = client.get_device_solar_data(device_id)
                        if solar_data:
                            device_obj.solar_data = solar_data
                    except Exception:
                        pass  # Solar data not available for this device

                    daily_data.devices.append(device_obj)
    except Exception:
        pass  # Device information not available

    # Try to get personal records
    try:
        personal_records_data = client.get_personal_record()
        if personal_records_data and isinstance(personal_records_data, dict):
            for record_type, records in personal_records_data.items():
                if isinstance(records, list):
                    for record in records:
                        if isinstance(record, dict):
                            personal_record = PersonalRecord(
                                record_type=record_type,
                                value=record.get("value", 0),
                                date=record.get("date", ""),
                                activity_id=record.get("activityId"),
                            )
                            daily_data.personal_records.append(personal_record)
    except Exception:
        pass  # Personal records not available

    # Extract sleep data
    sleep_data = raw_data.get("sleep", {})
    sleep_dur_seconds = _safe_get(sleep_data, ["dailySleepDTO", "sleepTimeSeconds"])
    daily_data.sleep_duration_hours = sleep_dur_seconds / 3600 if sleep_dur_seconds else 0
    daily_data.sleep_score = _safe_get(sleep_data, ["dailySleepDTO", "sleepScores", "overall", "value"])

    # Extract HRV data
    daily_data.hrv_last_night_avg = _safe_get(raw_data, ["hrv", "hrvSummary", "lastNightAvg"])

    # Extract stress data
    daily_data.avg_stress_level = _safe_get(raw_data, ["stress", "avgStressLevel"])

    # Extract resting heart rate (RHR)
    # First try from AllDayHR in both formats - nested and flat
    rhr_from_all_day_hr = _safe_get(raw_data, ["activities", "AllDayHR", "payload", "restingHeartRate"])
    # If new format, try with a direct path (from example data)
    if not rhr_from_all_day_hr:
        rhr_from_all_day_hr = _safe_get(raw_data, ["AllDayHR", "payload", "restingHeartRate"])

    if rhr_from_all_day_hr:
        daily_data.resting_hr = rhr_from_all_day_hr
    else:
        # Try from sleep data
        rhr_from_sleep = _safe_get(sleep_data, ["restingHeartRate"])
        if rhr_from_sleep:
            daily_data.resting_hr = rhr_from_sleep
        else:
            # Final fallback
            rhr_metric_map = _safe_get(
                raw_data, ["resting_hr", "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE"], []
            )
            daily_data.resting_hr = rhr_metric_map[0].get("value") if rhr_metric_map else 0

    # Extract body battery data
    sleep_bb_list = _safe_get(sleep_data, ["sleepBodyBattery"], [])
    bb_values_today = [bb.get("value") for bb in sleep_bb_list if bb.get("value") is not None]
    daily_data.body_battery_max = max(bb_values_today) if bb_values_today else 0
    daily_data.body_battery_min = min(bb_values_today) if bb_values_today else 0

    # Extract SpO2 data
    daily_data.avg_spo2 = _safe_get(sleep_data, ["wellnessSpO2SleepSummaryDTO", "averageSPO2"])

    # Extract respiration data
    daily_data.avg_breath_rate = _safe_get(raw_data, ["respiration", "avgSleepRespirationValue"])

    # Get calories from AllDayHR data first if available (preferred source for daily total)
    all_day_hr_data = _safe_get(raw_data, ["activities", "AllDayHR", "payload"], {})
    daily_total_calories = all_day_hr_data.get("activeCalories", 0)

    # If no active calories found, try the new format directly
    if daily_total_calories == 0:
        all_day_hr_data_new = _safe_get(raw_data, ["AllDayHR", "payload"], {})
        daily_total_calories = all_day_hr_data_new.get("activeCalories", 0)

    # Try to get intensity minutes data
    try:
        intensity_minutes_data = client.get_intensity_minutes_data(date)
        if intensity_minutes_data:
            daily_data.intensity_minutes_data = intensity_minutes_data
    except Exception:
        daily_data.intensity_minutes_data = None

    # Try to extract activities from both formats
    activities_payload_list = _safe_get(raw_data, ["activities", "ActivitiesForDay", "payload"], [])

    # Handle if this is the new direct format provided in the example
    if (not activities_payload_list or len(activities_payload_list) == 0) and "ActivitiesForDay" in raw_data:
        # New direct format from the example
        activities_payload_list = _safe_get(raw_data, ["ActivitiesForDay", "payload"], [])
        # Also check AllDayHR in the new format for calorie data
        all_day_hr_data_direct = _safe_get(raw_data, ["AllDayHR", "payload"], {})
        if not daily_total_calories:
            daily_total_calories = all_day_hr_data_direct.get("activeCalories", 0)

    # Try to get detailed activities
    try:
        activities_detailed = client.get_activities_by_date(date, date)
        if activities_detailed and isinstance(activities_detailed, list):
            # Process activities_detailed to add split summaries
            for activity in activities_detailed:
                activity_id = activity.get("activityId")
                if activity_id:
                    try:
                        splits = client.get_activity_split_summaries(activity_id)
                        activity["split_summaries"] = splits
                    except Exception:
                        pass  # Split data not available
            daily_data.activities_detailed = activities_detailed
    except Exception:
        daily_data.activities_detailed = None

    daily_total_intensity = 0

    if isinstance(activities_payload_list, list):
        for activity_item_data in activities_payload_list:
            if isinstance(activity_item_data, dict):
                # Check if this is a detailed activity or a summary with an error
                if "detailsFetchError" in activity_item_data:
                    # This is a summary activity where detailed fetch failed
                    # We still create an activity object with the available summary data
                    # and store the error message in the details field
                    summary_data = activity_item_data

                    activity = DailyActivity(
                        activity_type=_safe_get(summary_data, ["activityType", "typeKey"], "Unknown"),
                        duration_seconds=summary_data.get("duration", 0),
                        distance_meters=summary_data.get("distance", 0),
                        avg_hr=summary_data.get("averageHR", 0),
                        min_hr=None,
                        max_hr=None,
                        calories=summary_data.get("calories", 0),
                        moderate_intensity_minutes=summary_data.get("moderateIntensityMinutes", 0),
                        vigorous_intensity_minutes=summary_data.get("vigorousIntensityMinutes", 0),
                        activity_id=summary_data.get("activityId"),
                        details={"error": summary_data.get("detailsFetchError"), "summary": summary_data},
                    )
                else:
                    # This is a detailed activity or activity summary
                    # Extract data with prioritization:
                    # 1. Try summaryDTO first (which contains summary metrics)
                    # 2. Fall back to top-level keys in the detailed response
                    summary_dto = activity_item_data.get("summaryDTO", {})

                    # Get all required fields with proper fallbacks
                    activity_id = activity_item_data.get("activityId", None)

                    # Try to get activity type - account for different formats
                    activity_type = None
                    if _safe_get(summary_dto, ["activityType", "typeKey"], None):
                        activity_type = _safe_get(summary_dto, ["activityType", "typeKey"], None)
                    elif _safe_get(activity_item_data, ["activityType", "typeKey"], None):
                        activity_type = _safe_get(activity_item_data, ["activityType", "typeKey"], None)
                    else:
                        # If we can't find typeKey, try to get activityName as fallback
                        activity_type = activity_item_data.get("activityName", "Unknown")

                    duration_seconds = summary_dto.get("duration", None) or activity_item_data.get("duration", 0)
                    distance_meters = summary_dto.get("distance", None) or activity_item_data.get("distance", 0)
                    avg_hr = summary_dto.get("averageHR", None) or activity_item_data.get("averageHR", 0)
                    min_hr = summary_dto.get("minHR", None) or activity_item_data.get("minHeartRate", None)
                    max_hr = summary_dto.get("maxHR", None) or activity_item_data.get("maxHeartRate", None)
                    calories = summary_dto.get("calories", None) or activity_item_data.get("calories", 0)

                    # Get intensity minutes with proper fallbacks
                    moderate_intensity_minutes = summary_dto.get(
                        "moderateIntensityMinutes", None
                    ) or activity_item_data.get("moderateIntensityMinutes", 0)
                    vigorous_intensity_minutes = summary_dto.get(
                        "vigorousIntensityMinutes", None
                    ) or activity_item_data.get("vigorousIntensityMinutes", 0)

                    # Try to get split summaries if available
                    split_summaries = None
                    if activity_id:
                        try:
                            # Try to get from the pre-processed detailed activities
                            if daily_data.activities_detailed:
                                for detailed_activity in daily_data.activities_detailed:
                                    if str(detailed_activity.get("activityId")) == str(activity_id):
                                        split_summaries = detailed_activity.get("split_summaries")
                                        break

                            # If not found, try to fetch directly
                            if not split_summaries:
                                split_summaries = client.get_activity_split_summaries(activity_id)
                        except Exception:
                            pass  # Split data not available

                    # Create the activity object with detailed information
                    activity = DailyActivity(
                        activity_type=activity_type,
                        duration_seconds=duration_seconds,
                        distance_meters=distance_meters,
                        avg_hr=avg_hr,
                        min_hr=min_hr,
                        max_hr=max_hr,
                        calories=calories,
                        moderate_intensity_minutes=moderate_intensity_minutes,
                        vigorous_intensity_minutes=vigorous_intensity_minutes,
                        activity_id=activity_id,
                        details=activity_item_data,  # Store the full detailed response
                        split_summaries=split_summaries,  # Store split data if available
                    )

                # Add to daily data and update totals
                daily_data.activities.append(activity)

                # Only add to daily totals if we don't have the all-day data
                # This ensures we prefer the all-day total when available
                if daily_total_calories == 0:
                    daily_total_calories += activity.calories

                daily_total_intensity += activity.moderate_intensity_minutes + activity.vigorous_intensity_minutes

    # Set the daily totals
    daily_data.calories_burned = daily_total_calories
    daily_data.intensity_minutes = daily_total_intensity

    return daily_data


def _safe_sum(seq: list[Any]) -> float:
    """
    Calculate sum of a sequence, safely handling non-numeric values.

    Args:
        seq: List of values, potentially containing non-numeric items.

    Returns:
        Sum of numeric values in the sequence.
    """
    return sum(v for v in seq if isinstance(v, (int, float)))


def _safe_mean(seq: list[Any]) -> float:
    """
    Calculate average of a sequence, safely handling non-numeric values.

    Args:
        seq: List of values, potentially containing non-numeric items.

    Returns:
        Average of numeric values in the sequence.
    """
    nums = [v for v in seq if isinstance(v, (int, float))]
    return mean(nums) if nums else 0.0


def _trend(vals: list[float]) -> str:
    """
    Simple % change between first half and second half of the week.

    Args:
        vals: List of values to calculate trend for.

    Returns:
        String representation of trend with arrow and percentage.
    """
    if len(vals) < 7:
        return "—"
    first_avg, last_avg = _safe_mean(vals[:4]), _safe_mean(vals[3:])
    if first_avg == 0:
        return "—"
    pct = (last_avg - first_avg) / first_avg * 100
    arrow = "↑" if pct >= 0 else "↓"
    return f"{arrow} {pct:+.1f}%"


def format_markdown(week_data: list[GarminDailyData]) -> str:
    """
    Formats the weekly Garmin data into a Markdown report.

    Args:
        week_data: A list of GarminDailyData objects, each containing the health
                   and fitness metrics for a specific day.

    Returns:
        A string containing the formatted Markdown report.
    """
    if not week_data:
        return "# Garmin Health & Fitness Report: Error\n\nNo data available for the week."

    start = week_data[0].date
    end = week_data[-1].date

    # Extract data for weekly aggregates
    steps_vals = [d.steps for d in week_data]
    floors_vals = [d.floors_climbed for d in week_data]
    sleep_dur_vals = [d.sleep_duration_hours for d in week_data]
    sleep_score_vals = [d.sleep_score for d in week_data]
    hrv_vals = [d.hrv_last_night_avg for d in week_data]
    calories_vals = [d.calories_burned for d in week_data]
    intensity_vals = [d.intensity_minutes for d in week_data]
    stress_vals = [d.avg_stress_level for d in week_data]
    rhr_vals = [d.resting_hr for d in week_data]
    bb_max_vals = [d.body_battery_max for d in week_data]
    bb_min_vals = [d.body_battery_min for d in week_data]
    spo2_vals = [d.avg_spo2 for d in week_data]
    breath_vals = [d.avg_breath_rate for d in week_data]
    hydration_vals = [d.hydration_amount_ml for d in week_data]

    md: list[str] = [f"# Garmin Health & Fitness Report: {start} – {end}\n"]

    # Weekly overview table
    md += [
        "## Weekly Overview",
        "| Metric                     | Daily Average    | Total            | Trend        |",
        "|----------------------------|------------------|------------------|--------------|",
        f"| Steps                      | {_safe_mean(steps_vals):,.0f}       "
        f"| {_safe_sum(steps_vals):,.0f}       | {_trend(steps_vals)}     |",
        f"| Floors Climbed             | {_safe_mean(floors_vals):,.1f}       "
        f"| {_safe_sum(floors_vals):,.0f}       | {_trend(floors_vals)}     |",
        f"| Sleep Duration             | {_safe_mean(sleep_dur_vals):.1f} h      "
        f"| {_safe_sum(sleep_dur_vals):.1f} h      | {_trend(sleep_dur_vals)} |",
        f"| Sleep Score                | {_safe_mean(sleep_score_vals):.0f}         "
        f"| –                | {_trend(sleep_score_vals)} |",
        f"| HRV (Last Night Avg)       | {_safe_mean(hrv_vals):.0f} ms        "
        f"| –                | {_trend(hrv_vals)}     |",
        f"| Calories Burned (Activity) | {_safe_mean(calories_vals):,.0f}     "
        f"| {_safe_sum(calories_vals):,.0f}     | {_trend(calories_vals)} |",
        f"| Intensity Minutes          | {_safe_mean(intensity_vals):.0f} min      "
        f"| {_safe_sum(intensity_vals):.0f} min      | {_trend(intensity_vals)} |",
        f"| Avg Stress Level           | {_safe_mean(stress_vals):.0f}         | –                "
        f"| {_trend(stress_vals)} |",
        f"| Resting HR                 | {_safe_mean(rhr_vals):.0f} bpm       | –                "
        f"| {_trend(rhr_vals)}     |",
        f"| Body Battery (Sleep Range) | {_safe_mean(bb_max_vals):.0f}–{_safe_mean(bb_min_vals):.0f} "
        f"| –                | {_trend(bb_max_vals)}     |",
        f"| Avg Blood Oxygen (Sleep)   | {_safe_mean(spo2_vals):.1f}%       | –                "
        f"| {_trend(spo2_vals)}    |",
        f"| Avg Breath Rate (Sleep)    | {_safe_mean(breath_vals):.1f} br/min   | –                "
        f"| {_trend(breath_vals)}    |",
        f"| Hydration                  | {_safe_mean(hydration_vals):.0f} ml      | {_safe_sum(hydration_vals):.0f} ml "
        f"     | {_trend(hydration_vals)}    |",
        "",
    ]

    # Add day-by-day comparison table
    day_names = []
    for day_data in week_data:
        try:
            ddate = dt.datetime.fromisoformat(day_data.date)
            day_names.append(ddate.strftime("%a %m/%d"))  # Format like "Mon 04/15"
        except ValueError:
            day_names.append("Unknown")

    # Build day-by-day table header
    md += [
        "## Daily Comparison",
        "| Metric | " + " | ".join(day_names) + " |",
        "|--------|" + "|".join(["-----" for _ in day_names]) + "|",
    ]

    # Add rows for each metric
    metric_data = [
        ("Steps", [f"{d.steps:,.0f}" for d in week_data]),
        ("Floors", [f"{d.floors_climbed:,.0f}" for d in week_data]),
        ("Sleep (h)", [f"{d.sleep_duration_hours:.1f}" for d in week_data]),
        ("Sleep Score", [f"{d.sleep_score:.0f}" for d in week_data]),
        ("HRV (ms)", [f"{d.hrv_last_night_avg:.0f}" for d in week_data]),
        ("Calories", [f"{d.calories_burned:,.0f}" for d in week_data]),
        ("Intensity (min)", [f"{d.intensity_minutes:.0f}" for d in week_data]),
        ("Stress Level", [f"{d.avg_stress_level:.0f}" for d in week_data]),
        ("Resting HR (bpm)", [f"{d.resting_hr:.0f}" for d in week_data]),
        ("Body Battery Max", [f"{d.body_battery_max:.0f}" for d in week_data]),
        ("Body Battery Min", [f"{d.body_battery_min:.0f}" for d in week_data]),
        ("SpO2 (%)", [f"{d.avg_spo2:.1f}" for d in week_data]),
        ("Breath Rate", [f"{d.avg_breath_rate:.1f}" for d in week_data]),
        ("Hydration (ml)", [f"{d.hydration_amount_ml:.0f}" for d in week_data]),
    ]

    for metric_name, values in metric_data:
        md.append(f"| {metric_name} | " + " | ".join(values) + " |")

    md.append("")  # Empty line after table

    # Daily summaries section
    md.append("## Daily Summaries\n")

    # Per‑day detail rows with improved formatting
    for day_data in week_data:
        try:
            ddate = dt.datetime.fromisoformat(day_data.date)
            day_name = ddate.strftime("%A")
        except ValueError:
            day_name = "Unknown Day"

        md.append(f"### {day_name}, {day_data.date}\n")

        # Format daily summary in clearer sections
        md += [
            "#### Wellness Metrics",
            f"- **Steps**: {day_data.steps:,.0f}",
            f"- **Floors Climbed**: {day_data.floors_climbed:,.0f}",
            f"- **Resting Heart Rate**: {day_data.resting_hr:.0f} bpm",
            f"- **Stress Level (Avg)**: {day_data.avg_stress_level:.0f}",
            f"- **Body Battery**: Max {day_data.body_battery_max:.0f}, Min {day_data.body_battery_min:.0f}",
            f"- **Hydration**: {day_data.hydration_amount_ml:.0f} ml / {day_data.hydration_goal_ml:.0f} ml goal",
        ]

        # Add fitness age if available
        if day_data.fitness_age:
            md.append(f"- **Fitness Age**: {day_data.fitness_age} years")

        md += [
            "",
            "#### Sleep Metrics",
            f"- **Duration**: {day_data.sleep_duration_hours:.1f} hours",
            f"- **Sleep Score**: {day_data.sleep_score:.0f}",
            f"- **HRV (Last Night Avg)**: {day_data.hrv_last_night_avg:.0f} ms",
            f"- **Blood Oxygen (Sleep Avg)**: {day_data.avg_spo2:.1f}%",
            f"- **Breath Rate (Sleep Avg)**: {day_data.avg_breath_rate:.1f} br/min",
            "",
            "#### Activity Summary",
            f"- **Calories Burned**: {day_data.calories_burned:,.0f}",
            f"- **Intensity Minutes**: {day_data.intensity_minutes:.0f}",
            "",
        ]

        # Display personal records if available
        if day_data.personal_records:
            md.append("#### Personal Records")
            for record in day_data.personal_records:
                md.append(f"- **{record.record_type}**: {record.value} ({record.date})")
            md.append("")

        # Activities section
        if day_data.activities:
            md.append("#### Recorded Activities")
            for activity in day_data.activities:
                duration_fmt = str(dt.timedelta(seconds=round(activity.duration_seconds)))
                distance_km = activity.distance_meters / 1000

                activity_info = [
                    f"- **{activity.activity_type}**\n",
                    f"  - Duration: {duration_fmt}\n",
                    f"  - Distance: {distance_km:.2f} km\n",
                    f"  - Avg HR: {activity.avg_hr:.0f} bpm",
                ]

                if activity.min_hr and activity.max_hr:
                    activity_info.append(f" (Min: {activity.min_hr:.0f}, Max: {activity.max_hr:.0f})")

                activity_info.append(f"\n  - Calories: {activity.calories:,.0f}")

                # Add split data if available
                if activity.split_summaries:
                    activity_info.append("\n  - Splits:")
                    for i, split in enumerate(activity.split_summaries.get("splits", [])):
                        split_distance = split.get("distance", 0) / 1000  # Convert to km
                        split_time = split.get("movingDuration", 0)
                        pace = split_time / 60 / split_distance if split_distance > 0 else 0
                        pace_min = int(pace)
                        pace_sec = int((pace - pace_min) * 60)

                        activity_info.append(
                            f"\n    - Split {i+1}: {split_distance:.2f} km @ {pace_min}:{pace_sec:02d} min/km"
                        )

                md.append("".join(activity_info))

        else:
            md.append("#### Recorded Activities\n- No activities recorded for this day")

        md.append("")  # Add a blank line between days

    return "\n".join(md)
