"""
Constants for the Garmin data analysis framework.

This module defines constants used throughout the analysis framework, including:
- Thresholds for baseline deviation statuses
- Configuration constants for baseline calculations
- Reference values for health metrics
"""


# Thresholds for Z-scores in baseline comparisons
class BaselineThresholds:
    """Threshold values for baseline comparisons using Z-scores."""

    # For metrics where lower is better (e.g., RHR)
    LOWER_IS_BETTER_OPTIMAL = -0.75  # Z-score threshold for optimal status
    NORMAL_UPPER = 0.75  # Upper bound for normal status
    SLIGHT_DEVIATION_UPPER = 1.5  # Z-score threshold for slight deviation
    CONCERNING_UPPER = 2.0  # Z-score threshold for concerning status

    # For metrics where higher is better (e.g., HRV)
    HIGHER_IS_BETTER_OPTIMAL = 0.75  # Z-score threshold for optimal status
    NORMAL_LOWER = -0.75  # Lower bound for normal status
    SLIGHT_DEVIATION_LOWER = -1.5  # Z-score threshold for slight deviation
    CONCERNING_LOWER = -2.0  # Z-score threshold for concerning status

    # For metrics where both extremes are bad (e.g., stress)
    SYMMETRIC_NORMAL = 0.75  # Z-score threshold for normal status
    SYMMETRIC_SLIGHT_DEVIATION = 1.5  # Z-score threshold for slight deviation
    SYMMETRIC_CONCERNING = 2.0  # Z-score threshold for concerning status


# Baseline configuration constants
class BaselineConfig:
    """Configuration for baseline calculations."""

    DEFAULT_LOOKBACK_DAYS = 30  # Default number of days for baseline calculations
    SLEEP_BASELINE_DAYS = 30  # Days for sleep metrics baselines
    HRV_BASELINE_DAYS = 30  # Days for HRV baseline
    RHR_BASELINE_DAYS = 30  # Days for RHR baseline
    STRESS_BASELINE_DAYS = 30  # Days for stress baseline
    BODY_BATTERY_BASELINE_DAYS = 14  # Days for Body Battery baseline

    MIN_DAYS_FOR_BASELINE = 7  # Minimum number of days needed to establish a baseline
    MIN_DATA_POINTS_FOR_STDDEV = 3  # Minimum data points for standard deviation calculation


# Sleep reference values
class SleepReference:
    """Reference values for sleep metrics."""

    DEEP_SLEEP_MIN_PCT = 15  # Minimum healthy percentage of deep sleep
    DEEP_SLEEP_MAX_PCT = 25  # Maximum normal percentage of deep sleep
    REM_SLEEP_MIN_PCT = 15  # Minimum healthy percentage of REM sleep
    REM_SLEEP_MAX_PCT = 25  # Maximum normal percentage of REM sleep

    SLEEP_EFFICIENCY_MIN = 80  # Minimum healthy sleep efficiency (%)
    WASO_MAX_SECONDS = 30 * 60  # Maximum normal WASO (30 minutes)

    RECOMMENDED_SLEEP_HOURS = {  # Recommended sleep hours by age group
        "18-25": 7.0,  # 7-9 hours
        "26-64": 7.0,  # 7-9 hours
        "65+": 7.0,  # 7-8 hours
    }


# Heart rate and HRV reference values
class HrReference:
    """Reference values for heart rate and HRV metrics."""

    RHR_ATHLETE_MALE = {  # Resting heart rate ranges for male athletes
        "18-25": (45, 60),
        "26-35": (45, 61),
        "36-45": (46, 62),
        "46-55": (46, 63),
        "56-65": (47, 63),
        "65+": (47, 65),
    }

    RHR_ATHLETE_FEMALE = {  # Resting heart rate ranges for female athletes
        "18-25": (49, 63),
        "26-35": (49, 64),
        "36-45": (50, 64),
        "46-55": (50, 65),
        "56-65": (51, 65),
        "65+": (51, 67),
    }

    HRV_RMSSD_REFERENCE = {  # HRV RMSSD reference ranges by age and gender
        "male": {
            "18-25": (40, 80),
            "26-35": (35, 75),
            "36-45": (30, 70),
            "46-55": (25, 65),
            "56-65": (20, 60),
            "65+": (15, 55),
        },
        "female": {
            "18-25": (35, 75),
            "26-35": (30, 70),
            "36-45": (25, 65),
            "46-55": (20, 60),
            "56-65": (15, 55),
            "65+": (10, 50),
        },
    }


# JSON paths for extracting data from Garmin JSON
class JsonPaths:
    """JSON paths for extracting data from Garmin Connect JSON."""

    SLEEP = {
        "total_sleep_seconds": "$.dailySleepDTO.sleepTimeSeconds",
        "deep_sleep_seconds": "$.dailySleepDTO.deepSleepSeconds",
        "light_sleep_seconds": "$.dailySleepDTO.lightSleepSeconds",
        "rem_sleep_seconds": "$.dailySleepDTO.remSleepSeconds",
        "awake_seconds": "$.dailySleepDTO.awakeSleepSeconds",
        "sleep_start_timestamp": "$.dailySleepDTO.sleepStartTimestampGMT",
        "sleep_end_timestamp": "$.dailySleepDTO.sleepEndTimestampGMT",
        "resting_heart_rate": "$.dailySleepDTO.restingHeartRateInBeatsPerMinute",
        "avg_sleep_stress": "$.avgSleepStress",
    }

    HRV = {
        "nightly_avg": "$.hrvSummary.lastNightAvg",
        "weekly_avg": "$.hrvSummary.last7DayAvg",
    }

    STRESS = {
        "avg_stress_level": "$.avgStressLevel",
        "max_stress_level": "$.maxStressLevel",
        "stress_duration_seconds": "$.stressDurationSeconds",
        "rest_duration_seconds": "$.restDurationSeconds",
        "activity_duration_seconds": "$.activityDurationSeconds",
        "low_stress_duration_seconds": "$.lowStressDurationSeconds",
        "medium_stress_duration_seconds": "$.mediumStressDurationSeconds",
        "high_stress_duration_seconds": "$.highStressDurationSeconds",
    }

    BODY_BATTERY = {
        "charged": "$.bodyBatteryValueDescriptors.charged",
        "drained": "$.bodyBatteryValueDescriptors.drained",
        "values_array": "$.bodyBatteryValuesArray",  # Array of [timestamp, value] pairs
    }


# Data types defined in the database
class DataTypes:
    """Data types stored in the database."""

    SLEEP = "sleep"
    STRESS = "stress"
    HRV = "hrv"
    BODY_BATTERY = "body_battery"
    HEART_RATE = "heart_rate"
    RESTING_HEART_RATE = "resting_heart_rate"
    ACTIVITIES = "activities"
    SPO2 = "spo2"
    RESPIRATION = "respiration"
    FLOORS = "floors"
    HYDRATION = "hydration"
    STEPS = "steps"

    # List of all data types
    ALL = [
        SLEEP,
        STRESS,
        HRV,
        BODY_BATTERY,
        HEART_RATE,
        RESTING_HEART_RATE,
        ACTIVITIES,
        SPO2,
        RESPIRATION,
        FLOORS,
        HYDRATION,
        STEPS,
    ]

    # Mapping of analysis features to required data types
    ANALYSIS_REQUIREMENTS = {
        "sleep_quality": [SLEEP],
        "recovery": [SLEEP, HRV, BODY_BATTERY, STRESS],
        "stress_analysis": [STRESS, HEART_RATE, HRV],
        "readiness": [SLEEP, HRV, BODY_BATTERY, STRESS, RESTING_HEART_RATE],
    }
