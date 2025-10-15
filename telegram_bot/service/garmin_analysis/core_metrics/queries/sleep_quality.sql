-- sleep_quality.sql
-- SQL queries for calculating sleep quality metrics from Garmin data

-- Total Sleep Time (TST)
-- Calculates total sleep time in seconds (sum of deep, light, and REM sleep)
WITH sleep_data AS (
    SELECT
        json_data
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'sleep'
)
SELECT
    CAST(json_extract_string(json_data, '$.dailySleepDTO.deepSleepSeconds') AS INTEGER) AS deep_sleep_seconds,
    CAST(json_extract_string(json_data, '$.dailySleepDTO.lightSleepSeconds') AS INTEGER) AS light_sleep_seconds,
    CAST(json_extract_string(json_data, '$.dailySleepDTO.remSleepSeconds') AS INTEGER) AS rem_sleep_seconds,
    CAST(json_extract_string(json_data, '$.dailySleepDTO.awakeSleepSeconds') AS INTEGER) AS awake_seconds,
    CAST(json_extract_string(json_data, '$.dailySleepDTO.sleepStartTimestampGMT') AS BIGINT) AS sleep_start_timestamp,
    CAST(json_extract_string(json_data, '$.dailySleepDTO.sleepEndTimestampGMT') AS BIGINT) AS sleep_end_timestamp,
    CAST(json_extract_string(json_data, '$.dailySleepDTO.restingHeartRateInBeatsPerMinute') AS INTEGER) AS resting_heart_rate,
    CAST(json_extract_string(json_data, '$.avgSleepStress') AS DOUBLE) AS avg_sleep_stress,

    -- Total Sleep Time
    CAST(json_extract_string(json_data, '$.dailySleepDTO.deepSleepSeconds') AS INTEGER) +
    CAST(json_extract_string(json_data, '$.dailySleepDTO.lightSleepSeconds') AS INTEGER) +
    CAST(json_extract_string(json_data, '$.dailySleepDTO.remSleepSeconds') AS INTEGER) AS total_sleep_seconds
FROM sleep_data;

-- Sleep Efficiency (SE)
-- Calculates sleep efficiency as TST / (Time in Bed) * 100
WITH sleep_data AS (
    SELECT
        json_data
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'sleep'
),
sleep_times AS (
    SELECT
        CAST(json_extract_string(json_data, '$.dailySleepDTO.deepSleepSeconds') AS BIGINT) AS deep_s,
        CAST(json_extract_string(json_data, '$.dailySleepDTO.lightSleepSeconds') AS BIGINT) AS light_s,
        CAST(json_extract_string(json_data, '$.dailySleepDTO.remSleepSeconds') AS BIGINT) AS rem_s,
        CAST(json_extract_string(json_data, '$.dailySleepDTO.sleepStartTimestampGMT') AS BIGINT) AS start_ts,
        CAST(json_extract_string(json_data, '$.dailySleepDTO.sleepEndTimestampGMT') AS BIGINT) AS end_ts
    FROM sleep_data
)
SELECT
    CASE
        WHEN (end_ts - start_ts) > 0 THEN
            (deep_s + light_s + rem_s) * 100.0 / ((end_ts - start_ts)/1000) -- Timestamps are in ms
        ELSE NULL
    END AS sleep_efficiency_percentage
FROM sleep_times;

-- Sleep Stage Percentages
-- Calculates percentages of deep, light, and REM sleep
WITH sleep_data AS (
    SELECT
        json_data
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'sleep'
),
sleep_times AS (
    SELECT
        CAST(json_extract_string(json_data, '$.dailySleepDTO.deepSleepSeconds') AS DOUBLE) AS deep_s,
        CAST(json_extract_string(json_data, '$.dailySleepDTO.lightSleepSeconds') AS DOUBLE) AS light_s,
        CAST(json_extract_string(json_data, '$.dailySleepDTO.remSleepSeconds') AS DOUBLE) AS rem_s
    FROM sleep_data
),
total_sleep AS (
    SELECT deep_s + light_s + rem_s AS tst_s FROM sleep_times
)
SELECT
    CASE WHEN (SELECT tst_s FROM total_sleep) > 0 THEN (SELECT deep_s FROM sleep_times) * 100.0 / (SELECT tst_s FROM total_sleep) ELSE NULL END AS deep_sleep_percentage,
    CASE WHEN (SELECT tst_s FROM total_sleep) > 0 THEN (SELECT light_s FROM sleep_times) * 100.0 / (SELECT tst_s FROM total_sleep) ELSE NULL END AS light_sleep_percentage,
    CASE WHEN (SELECT tst_s FROM total_sleep) > 0 THEN (SELECT rem_s FROM sleep_times) * 100.0 / (SELECT tst_s FROM total_sleep) ELSE NULL END AS rem_sleep_percentage
FROM sleep_times;

-- WASO (Wake After Sleep Onset) - Simplified version
-- Calculates approximate WASO by summing all 'awake' periods
WITH sleep_data AS (
    SELECT
        json_data
    FROM garmin_raw_data
    WHERE user_id = ?
      AND date = ?
      AND data_type = 'sleep'
)
SELECT
    CAST(json_extract_string(json_data, '$.dailySleepDTO.awakeSleepSeconds') AS INTEGER) AS waso_seconds
FROM sleep_data;

-- Get all sleep metrics in one query
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
),
total_sleep AS (
    SELECT
        deep_sleep_seconds + light_sleep_seconds + rem_sleep_seconds AS total_sleep_seconds,
        sleep_end_timestamp - sleep_start_timestamp AS time_in_bed_ms,
        deep_sleep_seconds, light_sleep_seconds, rem_sleep_seconds,
        awake_seconds, sleep_start_timestamp, sleep_end_timestamp,
        resting_heart_rate, avg_sleep_stress
    FROM sleep_metrics
)
SELECT
    total_sleep_seconds,
    deep_sleep_seconds,
    light_sleep_seconds,
    rem_sleep_seconds,
    awake_seconds,
    resting_heart_rate,
    avg_sleep_stress,
    sleep_start_timestamp,
    sleep_end_timestamp,
    -- Sleep efficiency
    CASE
        WHEN time_in_bed_ms > 0 THEN
            total_sleep_seconds * 100.0 / (time_in_bed_ms/1000)
        ELSE NULL
    END AS sleep_efficiency_pct,
    -- Sleep stage percentages
    CASE WHEN total_sleep_seconds > 0 THEN deep_sleep_seconds * 100.0 / total_sleep_seconds ELSE NULL END AS deep_sleep_pct,
    CASE WHEN total_sleep_seconds > 0 THEN light_sleep_seconds * 100.0 / total_sleep_seconds ELSE NULL END AS light_sleep_pct,
    CASE WHEN total_sleep_seconds > 0 THEN rem_sleep_seconds * 100.0 / total_sleep_seconds ELSE NULL END AS rem_sleep_pct
FROM total_sleep;
