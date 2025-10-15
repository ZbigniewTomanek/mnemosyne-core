-- ans_status.sql
-- SQL queries for calculating recovery and ANS (Autonomic Nervous System) metrics

-- Resting Heart Rate (RHR)
-- Extract resting heart rate from both sleep data and daily_summary
WITH rhr_sources AS (
    SELECT
        CAST(json_extract_string(json_data, '$.dailySleepDTO.restingHeartRateInBeatsPerMinute') AS INTEGER) AS sleep_rhr
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'sleep'

    UNION ALL

    SELECT
        CAST(json_extract_string(json_data, '$.restingHeartRate') AS INTEGER) AS sleep_rhr
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'resting_heart_rate'
)
SELECT
    COALESCE(MIN(sleep_rhr), NULL) AS resting_heart_rate
FROM rhr_sources
WHERE sleep_rhr IS NOT NULL;

-- Nightly HRV (RMSSD-based)
-- Extract last night's average HRV
SELECT
    CAST(json_extract_string(json_data, '$.hrvSummary.lastNightAvg') AS DOUBLE) AS nightly_hrv_rmssd
FROM garmin_raw_data
WHERE user_id = ?
  AND date = ?
  AND data_type = 'hrv'
  AND json_extract_string(json_data, '$.hrvSummary.lastNightAvg') IS NOT NULL;

-- 7-Day Rolling Average HRV
-- Calculate smoothed trend of nightly HRV
WITH daily_hrv AS (
    SELECT
        date,
        CAST(json_extract_string(json_data, '$.hrvSummary.lastNightAvg') AS DOUBLE) AS hrv_value
    FROM garmin_raw_data
    WHERE user_id = ?
      AND data_type = 'hrv'
      AND json_extract_string(json_data, '$.hrvSummary.lastNightAvg') IS NOT NULL
      AND date BETWEEN (? - INTERVAL '6 days') AND ?
)
SELECT
    AVG(hrv_value) AS hrv_7d_rolling_avg,
    COUNT(*) AS days_with_data
FROM daily_hrv;

-- Body Battery Dynamics
-- Get Body Battery metrics for the day
WITH bb_data AS (
    SELECT json_data
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'body_battery'
),
stress_data AS (
    SELECT json_data
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'stress'
),
bb_metrics AS (
    -- Try to get from body_battery data type
    SELECT
        CAST(json_extract_string(json_data, '$.bodyBatteryValueDescriptors.charged') AS INTEGER) AS charged,
        CAST(json_extract_string(json_data, '$.bodyBatteryValueDescriptors.drained') AS INTEGER) AS drained
    FROM bb_data

    UNION ALL

    -- Fallback to values in stress data (sometimes BB is in there)
    SELECT
        CAST(json_extract_string(json_data, '$.bodyBatteryValueDescriptors.charged') AS INTEGER) AS charged,
        CAST(json_extract_string(json_data, '$.bodyBatteryValueDescriptors.drained') AS INTEGER) AS drained
    FROM stress_data
),
bb_values AS (
    SELECT *
    FROM (
        -- Try to get from body_battery data type
        SELECT
            CAST(entry[1] AS INTEGER) AS bb_value
        FROM bb_data,
             JSON_EXTRACT(json_data, '$.bodyBatteryValuesArray') AS entries,
             UNNEST(entries) AS entry

        UNION ALL

        -- Fallback to values in stress data
        SELECT
            CAST(entry[1] AS INTEGER) AS bb_value
        FROM stress_data,
             JSON_EXTRACT(json_data, '$.bodyBatteryValuesArray') AS entries,
             UNNEST(entries) AS entry
    ) t
    WHERE bb_value IS NOT NULL
)
SELECT
    MAX(bb_value) AS body_battery_max,
    MIN(bb_value) AS body_battery_min,
    (SELECT charged FROM bb_metrics WHERE charged IS NOT NULL LIMIT 1) AS body_battery_charged,
    (SELECT drained FROM bb_metrics WHERE drained IS NOT NULL LIMIT 1) AS body_battery_drained,
    MAX(bb_value) - MIN(bb_value) AS body_battery_net_change
FROM bb_values;

-- Average Stress Level
-- Calculate average stress level for the day
SELECT
    CAST(json_extract_string(json_data, '$.avgStressLevel') AS DOUBLE) AS avg_stress_level,
    CAST(json_extract_string(json_data, '$.maxStressLevel') AS DOUBLE) AS max_stress_level
FROM garmin_raw_data
WHERE user_id = ?
  AND date = ?
  AND data_type = 'stress'
  AND json_extract_string(json_data, '$.avgStressLevel') IS NOT NULL;

-- Get all recovery metrics in one query
WITH sleep_data AS (
    SELECT
        CAST(json_extract_string(json_data, '$.dailySleepDTO.restingHeartRateInBeatsPerMinute') AS INTEGER) AS sleep_rhr
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
        json_data AS stress_json -- Keep JSON for body battery extraction
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
),
bb_values AS (
    SELECT
        bb_value
    FROM (
        -- From body_battery data type
        SELECT
            CAST(entry[1] AS INTEGER) AS bb_value
        FROM body_battery_data,
             JSON_EXTRACT(bb_json, '$.bodyBatteryValuesArray') AS entries,
             UNNEST(entries) AS entry

        UNION ALL

        -- From stress data type
        SELECT
            CAST(entry[1] AS INTEGER) AS bb_value
        FROM stress_data,
             JSON_EXTRACT(stress_json, '$.bodyBatteryValuesArray') AS entries,
             UNNEST(entries) AS entry
    ) t
    WHERE bb_value IS NOT NULL
)
SELECT
    -- Resting Heart Rate (take the lowest value available)
    COALESCE((SELECT sleep_rhr FROM sleep_data), (SELECT direct_rhr FROM rhr_data)) AS resting_heart_rate,

    -- HRV values
    (SELECT nightly_hrv_rmssd FROM hrv_data) AS hrv_rmssd,
    (SELECT hrv_7d_avg FROM hrv_rolling) AS hrv_7day_avg,

    -- Body Battery
    (SELECT MAX(bb_value) FROM bb_values) AS body_battery_max,
    (SELECT MIN(bb_value) FROM bb_values) AS body_battery_min,

    -- Body Battery charged/drained (try both sources)
    COALESCE(
        (SELECT CAST(json_extract_string(bb_json, '$.bodyBatteryValueDescriptors.charged') AS INTEGER) FROM body_battery_data),
        (SELECT CAST(json_extract_string(stress_json, '$.bodyBatteryValueDescriptors.charged') AS INTEGER) FROM stress_data)
    ) AS body_battery_charged,

    COALESCE(
        (SELECT CAST(json_extract_string(bb_json, '$.bodyBatteryValueDescriptors.drained') AS INTEGER) FROM body_battery_data),
        (SELECT CAST(json_extract_string(stress_json, '$.bodyBatteryValueDescriptors.drained') AS INTEGER) FROM stress_data)
    ) AS body_battery_drained,

    -- Stress
    (SELECT avg_stress_level FROM stress_data) AS avg_stress_level,
    (SELECT max_stress_level FROM stress_data) AS max_stress_level;
