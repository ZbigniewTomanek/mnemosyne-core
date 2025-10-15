import asyncio
import dataclasses
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from garminconnect import Garmin, GarminConnectTooManyRequestsError
from loguru import logger

from telegram_bot.service.garmin_account_manager import GarminAccountManager

# Data classes imported from original script
from telegram_bot.service.garmin_data_models import (
    DailyActivity,
    GarminDailyData,
    _safe_mean,
    _safe_sum,
    daterange,
    extract_daily_data,
    format_markdown,
    get_daily_metrics,
)

# Configuration
RETRIES = 3
BACKOFF = 5  # seconds (multiplier for retry)


class GarminConnectService:
    """Service for interacting with Garmin Connect API."""

    def __init__(self, token_store_dir: Path):
        """
        Initialize the service with a token store directory.

        Args:
            token_store_dir: Directory to store user tokens.
        """
        self.account_manager = GarminAccountManager(token_store_dir)
        logger.info(f"Initialized GarminConnectService with token store at {token_store_dir}")

    async def authenticate_user(
        self, telegram_user_id: int, email: str, password: str
    ) -> Tuple[Union[bool, str], Optional[Any]]:
        """
        Authenticate a user with Garmin Connect and store their tokens.

        Args:
            telegram_user_id: The Telegram user ID to authenticate.
            email: Garmin Connect email address.
            password: Garmin Connect password.

        Returns:
            Tuple containing:
            - True if authentication was successful, "needs_mfa" if MFA is required, False on failure
            - MFA state data if MFA is required, error message on failure, None on success
        """
        user_token_dir = self.account_manager.get_user_token_path(telegram_user_id)
        user_token_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Authenticating user {telegram_user_id} with Garmin Connect")

        try:
            # Use the existing login function but store tokens in user-specific directory
            garmin = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
            result1, result2 = garmin.login()

            if result1 == "needs_mfa":
                logger.info(f"MFA required for user {telegram_user_id}")
                return "needs_mfa", result2

            # Save tokens to user's directory
            garmin.garth.dump(user_token_dir)
            logger.info(f"Authentication successful for user {telegram_user_id}")
            return True, None
        except Exception as e:
            logger.exception(f"Authentication error for user {telegram_user_id}: {e}")
            return False, str(e)

    async def handle_mfa(self, telegram_user_id: int, mfa_code: str, login_state) -> bool:
        """
        Complete the MFA authentication process.

        Args:
            telegram_user_id: The Telegram user ID.
            mfa_code: The MFA code provided by the user.
            login_state: The login state returned from the initial authentication.

        Returns:
            True if MFA authentication was successful, False otherwise.
        """
        user_token_dir = self.account_manager.get_user_token_path(telegram_user_id)

        logger.info(f"Processing MFA for user {telegram_user_id}")

        try:
            garmin = Garmin()
            garmin.resume_login(login_state, mfa_code)

            # Save tokens to user's directory
            garmin.garth.dump(user_token_dir)
            logger.info(f"MFA authentication successful for user {telegram_user_id}")
            return True
        except Exception as e:
            logger.exception(f"MFA error for user {telegram_user_id}: {e}")
            return False

    async def get_data_for_period(
        self,
        telegram_user_id: int,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        days: int = 7,
    ) -> List[GarminDailyData]:
        """
        Retrieve Garmin data for the specified period.
        Includes detailed activity data and all-day heart rate information.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date for data retrieval (optional).
            end_date: End date for data retrieval (optional).
            days: Number of days to retrieve if start_date or end_date is not provided.

        Returns:
            A list of GarminDailyData objects for the specified period.
        """
        client = self.account_manager.create_client(telegram_user_id)
        if not client:
            logger.warning(f"Could not create Garmin client for user {telegram_user_id}")
            return []

        # Get the date range
        date_range = daterange(start_date, end_date, days)
        logger.info(f"Retrieving data for user {telegram_user_id} from {date_range[0]} to {date_range[-1]}")

        # Extract data for each date
        all_data: List[GarminDailyData] = []
        for date in date_range:
            for attempt in range(RETRIES):
                try:
                    daily_data = extract_daily_data(client, date)
                    all_data.append(daily_data)
                    logger.debug(f"Retrieved data for {date}")
                    break
                except GarminConnectTooManyRequestsError:
                    sleep_seconds = BACKOFF * (attempt + 1)
                    logger.warning(f"Rate limit hit – retrying {date} in {sleep_seconds}s…")
                    await asyncio.sleep(sleep_seconds)
                except Exception as exc:
                    if attempt < RETRIES - 1:
                        sleep_seconds = BACKOFF * (attempt + 1)
                        logger.warning(f"Error processing data for {date}: {str(exc)}. Retrying in {sleep_seconds}s...")
                        await asyncio.sleep(sleep_seconds)
                    else:
                        logger.error(f"Failed to process data for {date} after {RETRIES} attempts: {str(exc)}")
                        # Create a minimal GarminDailyData object with error info
                        error_data = GarminDailyData(
                            date=date,
                            # Add a DailyActivity with the error message
                            activities=[
                                DailyActivity(
                                    activity_type="Error",
                                    duration_seconds=0,
                                    distance_meters=0,
                                    avg_hr=0,
                                    details={"error": f"Failed to fetch data: {str(exc)}"},
                                )
                            ],
                        )
                        all_data.append(error_data)
                        break
            else:
                logger.warning(f"Skipping {date} after {RETRIES} attempts due to rate limiting")
                # Create a minimal GarminDailyData object with rate limiting error info
                rate_limit_data = GarminDailyData(
                    date=date,
                    # Add a DailyActivity with the error message
                    activities=[
                        DailyActivity(
                            activity_type="Error",
                            duration_seconds=0,
                            distance_meters=0,
                            avg_hr=0,
                            details={"error": f"Rate limit exceeded after {RETRIES} attempts"},
                        )
                    ],
                )
                all_data.append(rate_limit_data)

        logger.info(f"Retrieved data for {len(all_data)} days for user {telegram_user_id}")
        return all_data

    async def generate_markdown_report(
        self,
        telegram_user_id: int,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        days: int = 7,
    ) -> str:
        """
        Generate a markdown report for the specified period.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date for the report (optional).
            end_date: End date for the report (optional).
            days: Number of days to include if start_date or end_date is not provided.

        Returns:
            Markdown-formatted report as a string.
        """
        logger.info(f"Generating markdown report for user {telegram_user_id}")
        data = await self.get_data_for_period(telegram_user_id, start_date, end_date, days)
        report = format_markdown(data)
        logger.info(f"Generated markdown report of {len(report)} characters")
        return report

    async def export_raw_json(
        self,
        telegram_user_id: int,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        Export comprehensive raw JSON data from Garmin Connect API.
        Includes detailed activity data, health metrics, performance metrics,
        device information, and more.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date for data export (optional).
            end_date: End date for data export (optional).
            days: Number of days to export if start_date or end_date is not provided.

        Returns:
            List of raw JSON data from the Garmin Connect API.
        """
        client = self.account_manager.create_client(telegram_user_id)
        if not client:
            logger.warning(f"Could not create Garmin client for user {telegram_user_id}")
            return []

        logger.info(f"Exporting raw JSON for user {telegram_user_id}")
        date_range = daterange(start_date, end_date, days)
        raw_data = []

        # Get device information (once, not per day)
        devices_data = await self._fetch_with_retry(client.get_devices)
        device_solar_data = {}

        # If devices are available, try to get solar data for each
        if devices_data and isinstance(devices_data, list):
            for device in devices_data:
                if device.get("deviceId"):
                    device_id = device.get("deviceId")
                    try:
                        # Use the first date in the range as a reference date
                        reference_date = date_range[0]
                        if isinstance(reference_date, dt.date):
                            reference_date_str = reference_date.isoformat()
                        else:
                            reference_date_str = reference_date  # Already a string

                        solar_data = await self._fetch_with_retry(
                            client.get_device_solar_data, device_id, reference_date_str
                        )
                        if solar_data:
                            device_solar_data[device_id] = solar_data
                    except Exception as exc:
                        logger.warning(f"Error fetching solar data for device {device_id}: {str(exc)}")

        # Get user's personal records (once, not per day)
        personal_records = await self._fetch_with_retry(client.get_personal_record)

        for date in date_range:
            daily_data = {}

            # Fetch daily metrics (existing function)
            try:
                # Get base daily metrics (steps, sleep, HRV, etc.)
                daily_metrics = await self._fetch_with_retry(get_daily_metrics, client, date)
                daily_data.update(daily_metrics)

                # Add additional data sources
                # 1. Intensity minutes data
                intensity_minutes = await self._fetch_with_retry(client.get_intensity_minutes_data, date)
                daily_data["intensity_minutes_detailed"] = intensity_minutes

                # 2. Floors data
                floors_data = await self._fetch_with_retry(client.get_floors, date)
                daily_data["floors"] = floors_data

                # 3. Hydration data
                hydration_data = await self._fetch_with_retry(client.get_hydration_data, date)
                daily_data["hydration"] = hydration_data

                # 4. Fitness age data (requires a date parameter for consistency)
                fitness_age_data = await self._fetch_with_retry(client.get_fitnessage_data, date)
                daily_data["fitness_age"] = fitness_age_data

                # 5. More comprehensive activities data
                activities_data = await self._fetch_with_retry(client.get_activities_by_date, date, date)

                if activities_data and isinstance(activities_data, list):
                    activity_details = []

                    for activity in activities_data:
                        activity_id = activity.get("activityId")
                        if activity_id:
                            # Get activity splits if available
                            try:
                                splits = await self._fetch_with_retry(client.get_activity_split_summaries, activity_id)
                                activity["split_summaries"] = splits
                            except Exception as exc:
                                logger.warning(f"Error fetching splits for activity {activity_id}: {str(exc)}")

                        activity_details.append(activity)

                    daily_data["activities_detailed"] = activity_details

                # Add device info to each day's data
                daily_data["user_devices"] = devices_data
                daily_data["device_solar_data"] = device_solar_data
                daily_data["personal_records"] = personal_records

                # Add the day's data to our results
                raw_data.append(daily_data)
                logger.debug(f"Retrieved comprehensive raw data for {date}")

            except GarminConnectTooManyRequestsError:
                # Handle rate limiting - already managed in _fetch_with_retry
                raw_data.append({"date": date, "error": f"Rate limit exceeded after {RETRIES} attempts"})
            except Exception as exc:
                logger.error(f"Failed to fetch data for {date} after {RETRIES} attempts: {str(exc)}")
                raw_data.append({"date": date, "error": f"Failed to fetch data: {str(exc)}"})

        logger.info(f"Exported comprehensive raw JSON data for {len(raw_data)} days")
        return raw_data

    async def export_aggregated_json(
        self,
        telegram_user_id: int,
        start_date: Optional[dt.date] = None,
        end_date: Optional[dt.date] = None,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        Export aggregated JSON data with processed metrics.

        Args:
            telegram_user_id: The Telegram user ID.
            start_date: Start date for data export (optional).
            end_date: End date for data export (optional).
            days: Number of days to export if start_date or end_date is not provided.

        Returns:
            Dictionary containing aggregated data.
        """
        logger.info(f"Exporting aggregated JSON for user {telegram_user_id}")
        data = await self.get_data_for_period(telegram_user_id, start_date, end_date, days)

        # Convert the GarminDailyData objects to dictionaries
        aggregated_data = {
            "period": {
                "start_date": data[0].date if data else None,
                "end_date": data[-1].date if data else None,
                "days": len(data),
            },
            "daily_data": [dataclasses.asdict(day) for day in data],
            "summary": self._calculate_summary(data),
        }

        logger.info(f"Exported aggregated JSON data for {len(data)} days")
        return aggregated_data

    async def _fetch_with_retry(self, func, *args, **kwargs):
        """
        Helper method to fetch data with retry logic and rate limiting handling.

        Args:
            func: The function to call
            *args: Arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function

        Returns:
            Data returned by the function or error dictionary
        """
        for attempt in range(RETRIES):
            try:
                result = func(*args, **kwargs)
                return result
            except GarminConnectTooManyRequestsError:
                sleep_seconds = BACKOFF * (attempt + 1)
                logger.warning(f"Rate limit hit while fetching {func.__name__} – retrying in {sleep_seconds}s…")
                await asyncio.sleep(sleep_seconds)
                if attempt == RETRIES - 1:
                    raise
            except Exception as exc:
                if attempt < RETRIES - 1:
                    sleep_seconds = BACKOFF * (attempt + 1)
                    logger.warning(f"Error in {func.__name__}: {str(exc)}. Retrying in {sleep_seconds}s...")
                    await asyncio.sleep(sleep_seconds)
                else:
                    logger.error(f"Failed to execute {func.__name__} after {RETRIES} attempts: {str(exc)}")
                    raise

    def _calculate_summary(self, data: List[GarminDailyData]) -> Dict[str, Any]:
        """
        Calculate summary statistics from the daily data.

        Args:
            data: List of GarminDailyData objects.

        Returns:
            Dictionary containing summary statistics.
        """
        if not data:
            return {}

        # Extract data for summaries
        steps_vals = [d.steps for d in data]
        sleep_dur_vals = [d.sleep_duration_hours for d in data]
        sleep_score_vals = [d.sleep_score for d in data]
        hrv_vals = [d.hrv_last_night_avg for d in data]
        calories_vals = [d.calories_burned for d in data]
        intensity_vals = [d.intensity_minutes for d in data]
        stress_vals = [d.avg_stress_level for d in data]
        rhr_vals = [d.resting_hr for d in data]
        bb_max_vals = [d.body_battery_max for d in data]
        bb_min_vals = [d.body_battery_min for d in data]
        spo2_vals = [d.avg_spo2 for d in data]
        breath_vals = [d.avg_breath_rate for d in data]

        # Calculate trend values
        def _calculate_trend(vals: List[float]) -> Dict[str, Any]:
            if len(vals) < 7:
                return {"direction": "neutral", "percent_change": 0}

            first_avg = _safe_mean(vals[: len(vals) // 2])
            last_avg = _safe_mean(vals[len(vals) // 2 :])

            if first_avg == 0:
                return {"direction": "neutral", "percent_change": 0}

            pct = (last_avg - first_avg) / first_avg * 100
            direction = "up" if pct > 0 else ("down" if pct < 0 else "neutral")

            return {"direction": direction, "percent_change": round(pct, 2)}

        return {
            "steps": {
                "daily_avg": round(_safe_mean(steps_vals)),
                "total": round(_safe_sum(steps_vals)),
                "trend": _calculate_trend(steps_vals),
            },
            "sleep": {
                "duration_avg": round(_safe_mean(sleep_dur_vals), 2),
                "total_hours": round(_safe_sum(sleep_dur_vals), 2),
                "score_avg": round(_safe_mean(sleep_score_vals)),
                "trend": _calculate_trend(sleep_score_vals),
            },
            "heart_rate": {"resting_avg": round(_safe_mean(rhr_vals)), "trend": _calculate_trend(rhr_vals)},
            "hrv": {"avg": round(_safe_mean(hrv_vals)), "trend": _calculate_trend(hrv_vals)},
            "calories": {
                "daily_avg": round(_safe_mean(calories_vals)),
                "total": round(_safe_sum(calories_vals)),
                "trend": _calculate_trend(calories_vals),
            },
            "intensity": {
                "daily_avg": round(_safe_mean(intensity_vals)),
                "total": round(_safe_sum(intensity_vals)),
                "trend": _calculate_trend(intensity_vals),
            },
            "stress": {"avg": round(_safe_mean(stress_vals)), "trend": _calculate_trend(stress_vals)},
            "body_battery": {
                "max_avg": round(_safe_mean(bb_max_vals)),
                "min_avg": round(_safe_mean(bb_min_vals)),
                "trend": _calculate_trend(bb_max_vals),
            },
            "spo2": {"avg": round(_safe_mean(spo2_vals), 1), "trend": _calculate_trend(spo2_vals)},
            "respiration": {"avg": round(_safe_mean(breath_vals), 1), "trend": _calculate_trend(breath_vals)},
        }
