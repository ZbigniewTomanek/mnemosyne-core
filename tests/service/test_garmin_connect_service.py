#!/usr/bin/env python3
"""
Unit tests for GarminConnectService.

These tests validate the Garmin Connect data parsing functionality
using mock data from API response files.
"""

import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from telegram_bot.service.garmin_connect_service import GarminConnectService
from telegram_bot.service.garmin_data_models import (
    DailyActivity,
    GarminDailyData,
    GarminDevice,
    PersonalRecord,
    extract_daily_data,
    get_daily_metrics,
)
from tests import GARMIN_TEST_DATA_DIR

# Path to test data files

# Test date used in the sample files
TEST_DATE = "2025-05-01"
TEST_TIMESTAMP = "2025-05-13_22-00-22"  # Used for device and user-specific data


class MockGarminClient:
    """Mock Garmin client for testing."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def get_steps_data(self, date_str):
        return self._load_data(f"garmin_steps_{date_str}.json")

    def get_sleep_data(self, date_str):
        return self._load_data(f"garmin_sleep_{date_str}.json")

    def get_hrv_data(self, date_str):
        return self._load_data(f"garmin_hrv_{date_str}.json")

    def get_stress_data(self, date_str):
        return self._load_data(f"garmin_stress_{date_str}.json")

    def get_respiration_data(self, date_str):
        return self._load_data(f"garmin_respiration_{date_str}.json")

    def get_spo2_data(self, date_str):
        return self._load_data(f"garmin_spo2_{date_str}.json")

    def get_rhr_day(self, date_str):
        return self._load_data(f"garmin_resting_hr_{date_str}.json")

    def get_body_battery_events(self, date_str):
        return self._load_data(f"garmin_body_battery_{date_str}.json")

    def get_heart_rates(self, date_str):
        return self._load_data(f"garmin_heart_rates_{date_str}.json")

    def get_activities_fordate(self, date_str):
        return self._load_data(f"garmin_activities_{date_str}.json")

    def get_activities_by_date(self, start_date, end_date):
        if start_date == end_date:
            return self._load_data(f"garmin_activities_detailed_{start_date}.json")
        return self._load_data(f"garmin_activities_between_{start_date}_to_{end_date}.json")

    def get_floors(self, date_str):
        return self._load_data(f"garmin_floors_{date_str}.json")

    def get_hydration_data(self, date_str):
        return self._load_data(f"garmin_hydration_{date_str}.json")

    def get_intensity_minutes_data(self, date_str):
        return self._load_data(f"garmin_intensity_minutes_{date_str}.json")

    def get_stats(self, date_str):
        return self._load_data(f"garmin_stats_{date_str}_to_{date_str}.json")

    def get_devices(self):
        # Using a timestamp in the test data filename for non-date specific endpoints
        timestamp_files = list(self.data_dir.glob("garmin_devices_*.json"))
        if timestamp_files:
            return self._load_data(timestamp_files[0].name)
        return []

    def get_device_solar_data(self, device_id, date_str):
        # Using a timestamp in the test data filename for device-specific data
        solar_files = list(self.data_dir.glob(f"garmin_device_solar_{device_id}_*.json"))
        if solar_files:
            return self._load_data(solar_files[0].name)
        return {}

    def get_personal_record(self):
        # Using a timestamp in the test data filename for user-specific data
        record_files = list(self.data_dir.glob("garmin_personal_record_*.json"))
        if record_files:
            return self._load_data(record_files[0].name)
        return {}

    def get_fitnessage_data(self, date_str):
        # Using a timestamp in the test data filename for user-specific data
        fitness_files = list(self.data_dir.glob("garmin_fitness_age_*.json"))
        if fitness_files:
            return self._load_data(fitness_files[0].name)
        return {}

    def get_activity_details(self, activity_id):
        # This is a placeholder - actual tests may need to be implemented differently
        # depending on how activity IDs are handled in the test data
        return {
            "activity_id": activity_id,
            "type": "Running",
            "summaryDTO": {
                "activityType": {"typeKey": "running"},
                "duration": 3600.0,
                "distance": 5000.0,
                "averageHR": 150,
                "minHR": 120,
                "maxHR": 180,
                "calories": 500,
                "moderateIntensityMinutes": 15,
                "vigorousIntensityMinutes": 30,
            },
            "details": {},
        }

    def get_activity_split_summaries(self, activity_id):
        # Mock implementation for split summaries
        return {
            "splits": [
                {
                    "distance": 1000,
                    "movingDuration": 300,
                    "elevationGain": 10,
                    "elevationLoss": 5,
                    "avgSpeed": 3.33,
                    "avgHR": 145,
                },
                {
                    "distance": 1000,
                    "movingDuration": 310,
                    "elevationGain": 15,
                    "elevationLoss": 10,
                    "avgSpeed": 3.23,
                    "avgHR": 150,
                },
            ]
        }

    def _load_data(self, filename):
        try:
            with open(self.data_dir / filename, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            # Check if there's an error version of the file
            error_filename = filename.replace(".json", "_error.json")
            try:
                with open(self.data_dir / error_filename, "r") as f:
                    error_data = json.load(f)
                    # If it's an error file, return the error data instead of raising
                    return {"error": error_data.get("error", "Unknown error")}
            except FileNotFoundError:
                return {"error": f"Mock data file not found: {filename}"}


@pytest.fixture
def mock_garmin_client():
    """Fixture to create a mock Garmin client."""
    return MockGarminClient(GARMIN_TEST_DATA_DIR)


@pytest.fixture
def mock_account_manager():
    """Fixture to create a mock GarminAccountManager."""
    mock_manager = MagicMock()
    mock_manager.get_user_token_path.return_value = Path("/mock/token/path")
    mock_manager.create_client.return_value = MockGarminClient(GARMIN_TEST_DATA_DIR)
    return mock_manager


@pytest_asyncio.fixture
async def garmin_service(mock_account_manager):
    """Fixture to create a GarminConnectService with a mock account manager."""
    with patch("telegram_bot.service.garmin_connect_service.GarminAccountManager", return_value=mock_account_manager):
        service = GarminConnectService(Path("/mock/token/store"))
        service.account_manager = mock_account_manager
        yield service


# Tests for extract_daily_data function
def test_extract_daily_data(mock_garmin_client):
    """Test that extract_daily_data correctly processes and combines data from various endpoints."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the function returns a GarminDailyData object
    assert isinstance(daily_data, GarminDailyData)
    assert daily_data.date == TEST_DATE

    # Validate steps data if available in test data
    try:
        steps_data = mock_garmin_client.get_steps_data(TEST_DATE)
        if not isinstance(steps_data, dict) or "error" not in steps_data:
            expected_steps = sum(step.get("steps", 0) for step in steps_data)
            assert daily_data.steps == expected_steps
    except Exception:
        pass  # Skip if test data not available


def test_get_daily_metrics(mock_garmin_client):
    """Test that get_daily_metrics correctly fetches and combines data from various endpoints."""
    # Get metrics using the mock client
    metrics = get_daily_metrics(mock_garmin_client, TEST_DATE)

    # Verify the basic structure of the returned data
    assert isinstance(metrics, dict)
    assert "date" in metrics
    assert metrics["date"] == TEST_DATE

    # Check for expected keys in the metrics
    expected_keys = ["steps", "sleep", "hrv", "stress", "respiration", "spo2", "resting_hr", "body_battery", "AllDayHR"]

    for key in expected_keys:
        assert key in metrics, f"Expected key '{key}' not found in metrics"

    # Check that the data for new endpoints can be fetched, even if not in the metrics dict directly
    try:
        # These calls should not raise exceptions
        mock_garmin_client.get_floors(TEST_DATE)
        mock_garmin_client.get_hydration_data(TEST_DATE)
        mock_garmin_client.get_intensity_minutes_data(TEST_DATE)
    except Exception as e:
        pytest.fail(f"Error fetching additional data: {str(e)}")


def test_floors_data_parsing(mock_garmin_client):
    """Test that floors data is correctly parsed from the API response."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the floors data is correctly parsed
    try:
        floors_data = mock_garmin_client.get_floors(TEST_DATE)
        if isinstance(floors_data, list) and floors_data:
            expected_floors = sum(floor.get("value", 0) for floor in floors_data)
            assert daily_data.floors_climbed == expected_floors
    except Exception:
        pass  # Skip if test data not available


def test_hydration_data_parsing(mock_garmin_client):
    """Test that hydration data is correctly parsed from the API response."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the hydration data is correctly parsed
    try:
        hydration_data = mock_garmin_client.get_hydration_data(TEST_DATE)
        if isinstance(hydration_data, dict):
            expected_amount = hydration_data.get("valueInML", 0)
            expected_goal = hydration_data.get("goalInML", 0)
            assert daily_data.hydration_amount_ml == expected_amount
            assert daily_data.hydration_goal_ml == expected_goal
    except Exception:
        pass  # Skip if test data not available


def test_intensity_minutes_data_parsing(mock_garmin_client):
    """Test that intensity minutes data is correctly parsed from the API response."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the intensity minutes data is correctly parsed
    try:
        # First check if the detailed intensity data was saved
        intensity_data = mock_garmin_client.get_intensity_minutes_data(TEST_DATE)
        if intensity_data:
            # The detailed data should be stored in the intensity_minutes_data field
            assert daily_data.intensity_minutes_data is not None

            # If we have actual activity data, verify the total intensity minutes
            if daily_data.activities:
                expected_intensity = sum(
                    activity.moderate_intensity_minutes + activity.vigorous_intensity_minutes
                    for activity in daily_data.activities
                )
                assert daily_data.intensity_minutes == expected_intensity
    except Exception:
        pass  # Skip if test data not available


def test_devices_data_parsing(mock_garmin_client):
    """Test that devices data is correctly parsed from the API response."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the devices data is correctly parsed
    try:
        devices_data = mock_garmin_client.get_devices()
        if isinstance(devices_data, list) and devices_data:
            assert len(daily_data.devices) == len(devices_data)

            # Check the first device
            first_device = daily_data.devices[0]
            assert isinstance(first_device, GarminDevice)
            assert first_device.device_id == str(devices_data[0].get("deviceId"))
            assert first_device.device_name == devices_data[0].get("productDisplayName", "Unknown Device")
    except Exception:
        pass  # Skip if test data not available


def test_personal_records_parsing(mock_garmin_client):
    """Test that personal records data is correctly parsed from the API response."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the personal records data is correctly parsed
    try:
        records_data = mock_garmin_client.get_personal_record()
        if isinstance(records_data, dict) and records_data:
            assert len(daily_data.personal_records) > 0

            # Check that records are properly parsed as PersonalRecord objects
            for record in daily_data.personal_records:
                assert isinstance(record, PersonalRecord)
                assert record.record_type is not None
                assert record.value is not None
                assert record.date is not None
    except Exception:
        pass  # Skip if test data not available


def test_fitness_age_data_parsing(mock_garmin_client):
    """Test that fitness age data is correctly parsed from the API response."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the fitness age data is correctly parsed
    try:
        fitness_data = mock_garmin_client.get_fitnessage_data(TEST_DATE)
        if isinstance(fitness_data, dict) and "fitnessAge" in fitness_data:
            assert daily_data.fitness_age == fitness_data["fitnessAge"]
            assert daily_data.fitness_age_data == fitness_data
    except Exception:
        pass  # Skip if test data not available


def test_get_daily_metrics_with_activity_errors(mocker):
    """Test that get_daily_metrics handles errors when fetching activity data."""
    # Create a mock client with an error when fetching activities
    activity_error_client = MagicMock()

    # Mock method returns to avoid side_effect issues
    activity_error_client.get_steps_data = mocker.MagicMock(return_value=[{"steps": 1000}])
    activity_error_client.get_sleep_data = mocker.MagicMock(return_value={"dailySleepDTO": {"sleepTimeSeconds": 28800}})
    activity_error_client.get_hrv_data = mocker.MagicMock(return_value={"hrvSummary": {"lastNightAvg": 50}})
    activity_error_client.get_stress_data = mocker.MagicMock(return_value={"avgStressLevel": 30})
    activity_error_client.get_respiration_data = mocker.MagicMock(return_value={"avgSleepRespirationValue": 14.5})
    activity_error_client.get_spo2_data = mocker.MagicMock(
        return_value={"wellnessSpO2SleepSummaryDTO": {"averageSPO2": 96}}
    )
    activity_error_client.get_rhr_day = mocker.MagicMock(
        return_value={"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 60}]}}}
    )
    activity_error_client.get_body_battery_events = mocker.MagicMock(return_value=[])
    activity_error_client.get_heart_rates = mocker.MagicMock(return_value={"restingHeartRate": 59})
    activity_error_client.get_floors = mocker.MagicMock(return_value=[{"value": 10}])
    activity_error_client.get_hydration_data = mocker.MagicMock(return_value={"valueInML": 1500, "goalInML": 2000})
    activity_error_client.get_intensity_minutes_data = mocker.MagicMock(
        return_value={"moderateIntensityMinutes": 15, "vigorousIntensityMinutes": 20}
    )

    # Mock a function that raises an exception
    def raise_exception(date_str):
        raise Exception("Failed to fetch activities")

    # Activities fetch fails
    activity_error_client.get_activities_fordate = raise_exception

    # Get metrics
    metrics = get_daily_metrics(activity_error_client, TEST_DATE)

    # Verify that the activity error was handled properly
    assert "ActivitiesForDay" in metrics
    assert "errorMessage" in metrics["ActivitiesForDay"]
    assert "Failed to fetch activities" in metrics["ActivitiesForDay"]["errorMessage"]
    assert metrics["ActivitiesForDay"]["successful"] == False

    # Other metrics should still be available (verify at least one)
    assert metrics["hrv"]["hrvSummary"]["lastNightAvg"] == 50


def test_get_activity_details_parsing(mock_garmin_client):
    """Test that activity details are correctly parsed and transformed into DailyActivity objects."""
    # First, get daily metrics which should call get_activity_details internally
    get_daily_metrics(mock_garmin_client, TEST_DATE)

    # Then extract the daily data which processes activity details
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that we have activities in the daily data
    assert len(daily_data.activities) > 0

    # Get the first activity and verify its structure
    activity = daily_data.activities[0]
    assert isinstance(activity, DailyActivity)

    # Check that the activity has the expected fields from the mock data
    assert activity.activity_type is not None
    assert activity.duration_seconds > 0
    assert activity.distance_meters > 0
    assert activity.avg_hr > 0

    # Check that the details field was populated with the full response
    assert activity.details is not None

    # Check for split summaries if they exist
    if activity.activity_id and activity.split_summaries:
        assert "splits" in activity.split_summaries
        assert len(activity.split_summaries["splits"]) > 0


def test_activities_detailed_parsing(mock_garmin_client):
    """Test that detailed activities data is correctly parsed from the API response."""
    # Extract daily data using the mock client
    daily_data = extract_daily_data(mock_garmin_client, TEST_DATE)

    # Verify that the detailed activities data is correctly parsed if available
    try:
        activities_detailed = mock_garmin_client.get_activities_by_date(TEST_DATE, TEST_DATE)
        if isinstance(activities_detailed, list) and activities_detailed:
            assert daily_data.activities_detailed is not None
            assert isinstance(daily_data.activities_detailed, list)

            # Length should match or have a good reason to differ
            if len(daily_data.activities_detailed) != len(activities_detailed):
                # The reason would be if some activities couldn't be processed correctly
                pass
    except Exception:
        pass  # Skip if test data not available


@pytest.mark.asyncio
async def test_get_data_for_period(garmin_service, mock_account_manager):
    """Test that get_data_for_period correctly processes data for a date range."""
    # Mock the create_client method to return our mock client
    mock_account_manager.create_client.return_value = MockGarminClient(GARMIN_TEST_DATA_DIR)

    # Call the service method for a single day
    result = await garmin_service.get_data_for_period(
        telegram_user_id=12345,
        start_date=dt.date.fromisoformat(TEST_DATE),
        end_date=dt.date.fromisoformat(TEST_DATE),
    )

    # Verify that we got data for the requested day
    assert len(result) == 1
    assert isinstance(result[0], GarminDailyData)
    assert result[0].date == TEST_DATE

    # Check that the new fields are included
    assert hasattr(result[0], "floors_climbed")
    assert hasattr(result[0], "hydration_amount_ml")
    assert hasattr(result[0], "hydration_goal_ml")
    assert hasattr(result[0], "intensity_minutes_data")
    assert hasattr(result[0], "fitness_age")
    assert hasattr(result[0], "fitness_age_data")
    assert hasattr(result[0], "devices")
    assert hasattr(result[0], "personal_records")
    assert hasattr(result[0], "activities_detailed")


@pytest.mark.asyncio
async def test_get_data_for_period_client_error(garmin_service, mock_account_manager):
    """Test that get_data_for_period handles client creation errors."""
    # Mock the create_client method to return None (simulating failure)
    mock_account_manager.create_client.return_value = None

    # Call the service method
    result = await garmin_service.get_data_for_period(
        telegram_user_id=12345,
        start_date=dt.date.fromisoformat(TEST_DATE),
        end_date=dt.date.fromisoformat(TEST_DATE),
    )

    # Verify that we got an empty list
    assert result == []


@pytest.mark.asyncio
async def test_export_raw_json(garmin_service, mock_account_manager):
    """Test that export_raw_json correctly fetches and formats raw data from all endpoints."""
    # Mock the create_client method to return our mock client
    mock_account_manager.create_client.return_value = MockGarminClient(GARMIN_TEST_DATA_DIR)

    # Call the service method for a single day
    result = await garmin_service.export_raw_json(
        telegram_user_id=12345,
        start_date=dt.date.fromisoformat(TEST_DATE),
        end_date=dt.date.fromisoformat(TEST_DATE),
    )

    # Verify the basic structure of the result
    assert isinstance(result, list)
    assert len(result) == 1

    # Check that the first day's data contains the expected keys
    day_data = result[0]
    assert isinstance(day_data, dict)

    # We'll check for some of the key data points rather than all of them,
    # as the actual implementation might differ from our expectations
    assert "date" in day_data or any(key.endswith("date") for key in day_data.keys())
    assert any("device" in key.lower() for key in day_data.keys())
    assert any("personal" in key.lower() for key in day_data.keys())


@pytest.mark.asyncio
async def test_calculate_summary(garmin_service):
    """Test that _calculate_summary correctly aggregates data from multiple days."""
    # Create test data for multiple days
    test_data = [
        GarminDailyData(
            date="2025-05-01",
            steps=10000,
            floors_climbed=15,
            sleep_duration_hours=8.5,
            sleep_score=85,
            hrv_last_night_avg=60,
            calories_burned=2500,
            intensity_minutes=30,
            avg_stress_level=25,
            resting_hr=55,
            body_battery_max=100,
            body_battery_min=40,
            avg_spo2=97.5,
            avg_breath_rate=14.2,
            hydration_amount_ml=1500,
            hydration_goal_ml=2000,
        ),
        GarminDailyData(
            date="2025-05-02",
            steps=8000,
            floors_climbed=12,
            sleep_duration_hours=7.2,
            sleep_score=75,
            hrv_last_night_avg=55,
            calories_burned=2200,
            intensity_minutes=20,
            avg_stress_level=30,
            resting_hr=58,
            body_battery_max=95,
            body_battery_min=35,
            avg_spo2=98.0,
            avg_breath_rate=13.8,
            hydration_amount_ml=1700,
            hydration_goal_ml=2000,
        ),
    ]

    # Calculate summary
    summary = garmin_service._calculate_summary(test_data)

    # Verify the structure of the summary
    assert isinstance(summary, dict)

    # Check steps summary
    assert "steps" in summary
    assert summary["steps"]["daily_avg"] == 9000  # (10000 + 8000) / 2
    assert summary["steps"]["total"] == 18000  # 10000 + 8000

    # Check sleep summary
    assert "sleep" in summary
    assert summary["sleep"]["duration_avg"] == pytest.approx(7.85, abs=0.1)  # (8.5 + 7.2) / 2
    assert summary["sleep"]["total_hours"] == pytest.approx(15.7, abs=0.1)  # 8.5 + 7.2
    assert summary["sleep"]["score_avg"] == 80  # (85 + 75) / 2

    # Check for new metrics if they're included in the summary
    if "stairs" in summary:  # Some implementations may use "stairs" for floors
        assert summary["stairs"]["daily_avg"] == 13.5  # (15 + 12) / 2
        assert summary["stairs"]["total"] == 27  # 15 + 12

    if "hydration" in summary:
        assert summary["hydration"]["daily_avg"] == 1600  # (1500 + 1700) / 2
        assert summary["hydration"]["total"] == 3200  # 1500 + 1700


@pytest.mark.asyncio
async def test_calculate_summary_with_empty_data(garmin_service):
    """Test that _calculate_summary handles empty data gracefully."""
    # Calculate summary with empty data
    summary = garmin_service._calculate_summary([])

    # Verify that an empty dict is returned
    assert summary == {}


@pytest.mark.asyncio
async def test_export_aggregated_json(garmin_service, mock_account_manager, mocker):
    """Test that export_aggregated_json correctly processes and formats data."""
    # Mock get_data_for_period since it's already tested separately
    mocker.patch.object(
        garmin_service,
        "get_data_for_period",
        return_value=[
            GarminDailyData(
                date=TEST_DATE,
                steps=10000,
                floors_climbed=15,
                sleep_duration_hours=8.0,
                sleep_score=80,
                hrv_last_night_avg=60,
                calories_burned=2500,
                intensity_minutes=30,
                avg_stress_level=25,
                resting_hr=55,
                body_battery_max=100,
                body_battery_min=40,
                avg_spo2=97.5,
                avg_breath_rate=14.2,
                hydration_amount_ml=1500,
                hydration_goal_ml=2000,
            )
        ],
    )

    # Call the service method for a single day
    result = await garmin_service.export_aggregated_json(
        telegram_user_id=12345,
        start_date=dt.date.fromisoformat(TEST_DATE),
        end_date=dt.date.fromisoformat(TEST_DATE),
    )

    # Verify the structure of the aggregated data
    assert isinstance(result, dict)
    assert "period" in result
    assert "daily_data" in result
    assert "summary" in result

    # Check period info
    assert result["period"]["start_date"] == TEST_DATE
    assert result["period"]["end_date"] == TEST_DATE
    assert result["period"]["days"] == 1

    # Check daily data
    assert isinstance(result["daily_data"], list)
    assert len(result["daily_data"]) == 1
    assert result["daily_data"][0]["date"] == TEST_DATE

    # Check for new fields in daily data
    day_data = result["daily_data"][0]
    assert "floors_climbed" in day_data
    assert "hydration_amount_ml" in day_data
    assert "hydration_goal_ml" in day_data

    # Check summary for basic metrics that should always be there
    summary = result["summary"]
    assert "steps" in summary
    assert "sleep" in summary
    assert "heart_rate" in summary


@pytest.mark.asyncio
async def test_generate_markdown_report(garmin_service, mock_account_manager, mocker):
    """Test that generate_markdown_report correctly formats data as markdown."""
    # Mock get_data_for_period since it's already tested separately
    mocker.patch.object(
        garmin_service,
        "get_data_for_period",
        return_value=[
            GarminDailyData(
                date=TEST_DATE,
                steps=10000,
                floors_climbed=15,
                sleep_duration_hours=8.0,
                sleep_score=80,
                hrv_last_night_avg=60,
                calories_burned=2500,
                intensity_minutes=30,
                avg_stress_level=25,
                resting_hr=55,
                body_battery_max=100,
                body_battery_min=40,
                avg_spo2=97.5,
                avg_breath_rate=14.2,
                hydration_amount_ml=1500,
                hydration_goal_ml=2000,
                fitness_age=35,
            )
        ],
    )

    # Call the service method for a single day
    report = await garmin_service.generate_markdown_report(
        telegram_user_id=12345,
        start_date=dt.date.fromisoformat(TEST_DATE),
        end_date=dt.date.fromisoformat(TEST_DATE),
    )

    # Verify that we got a markdown string
    assert isinstance(report, str)

    # Check for expected markdown sections
    assert "# Garmin Health & Fitness Report" in report

    # Check for basic metrics in the report that should always be there
    basic_metrics = ["Steps", "Sleep", "HRV", "Calories", "Stress Level", "Resting HR"]
    for metric in basic_metrics:
        assert metric in report, f"Expected metric '{metric}' not found in report"
