# Garmin Data Reference

This document provides a comprehensive overview of the data exported from the Garmin Connect API used in this project.

## Top-Level Data Structure

The Garmin data is organized with the following top-level structure:

```json
{
  "period": {
    "start_date": "2025-05-01",
    "end_date": "2025-05-14",
    "days": 14
  },
  "data": {
    "2025-05-01": { /* Data for specific date */ },
    "2025-05-02": { /* Data for specific date */ },
    /* More dates... */
  },
  "data_types": [
    "device_solar_data",
    "fitness_age",
    "spo2",
    /* More data types... */
  ],
  "available_dates": [
    "2025-05-01",
    "2025-05-02",
    "2025-05-03"
    /* More dates... */
  ]
}
```

## Activity Data

### Activities
- Daily activities with detailed tracking:
```json
{
  "activityId": 18997891265,
  "activityName": "Sauna",
  "startTimeLocal": "2025-05-01 21:15:20",
  "startTimeGMT": "2025-05-01 19:15:20",
  "activityType": {
    "typeId": 4,
    "typeKey": "other",
    "parentTypeId": 17,
    "isHidden": false,
    "restricted": false,
    "trimmable": true
  },
  "distance": 0.0,
  "duration": 2390.202880859375,
  "calories": 331.0,
  "steps": 156,
  "averageHR": 116.0,
  "maxHR": 152.0
}
```
- Includes timestamps, distances, durations, calories, and steps
- Categorized by activity type with detailed type information
- Contains heart rate metrics, training effect data, and device information

### Steps
- Step counts at regular intervals throughout the day:
```json
[
  {
    "startGMT": "2025-04-30T22:00:00.0",
    "endGMT": "2025-04-30T22:15:00.0",
    "steps": 7,
    "pushes": 0,
    "primaryActivityLevel": "generic",
    "activityLevelConstant": true
  },
  /* More step intervals... */
]
```
- Tracks steps in 15-minute intervals
- Includes activity level classification
- Records wheelchair pushes where applicable

### Floors
- Floor climbing data with timestamps
- Usually stored as a time-series array with readings throughout the day
- Includes goal tracking and daily totals

### Intensity Minutes
```json
{
  "calendarDate": "2025-05-01",
  "moderateMinutes": 21,
  "vigorousMinutes": 14,
  "weekGoal": 150,
  "weeklyModerate": 21,
  "weeklyVigorous": 14,
  "weeklyTotal": 49,
  "imValuesArray": [
    [1746051300000, 11],  /* Timestamp, intensity value */
    /* More intensity values... */
  ]
}
```
- Tracks moderate and vigorous activity duration
- Records timestamps for activity intensity periods
- Includes weekly goals and progress tracking

## Health Metrics

### Heart Rate
- Heart rate readings throughout the day with timestamps
- Includes maximum, minimum, and average heart rates
- Often stored in time-series arrays with timestamps

### Heart Rate Variability (HRV)
```json
{
  "hrvSummary": {
    "calendarDate": "2025-05-01",
    "weeklyAvg": 70,
    "lastNightAvg": 66,
    "lastNight5MinHigh": 102,
    "baseline": {
      "lowUpper": 57,
      "balancedLow": 65,
      "balancedUpper": 110,
      "markerValue": 0.305542
    },
    "status": "BALANCED",
    "feedbackPhrase": "HRV_BALANCED_6",
    "createTimeStamp": "2025-05-01T08:46:33.839"
  }
}
```
- Important indicators of recovery and stress
- Includes baseline calculations and status assessments
- Provides weekly averages and overnight measurements

### Sleep
```json
{
  "dailySleepDTO": {
    "id": 1746055617000,
    "userProfilePK": 121573651,
    "calendarDate": "2025-05-01",
    "sleepTimeSeconds": 22200,
    "napTimeSeconds": 0,
    "sleepWindowConfirmed": true,
    "sleepStartTimestampGMT": 1746055617000,
    "sleepEndTimestampGMT": 1746078417000,
    "deepSleepSeconds": 1080,
    "lightSleepSeconds": 17520,
    "remSleepSeconds": 3600,
    "awakeSleepSeconds": 600,
    "sleepScores": {
      "overall": {
        "value": 71,
        "qualifierKey": "FAIR"
      },
      "deepPercentage": {
        "value": 5,
        "qualifierKey": "POOR"
      },
      "remPercentage": {
        "value": 16,
        "qualifierKey": "FAIR"
      },
      "lightPercentage": {
        "value": 79,
        "qualifierKey": "FAIR"
      }
    },
    "sleepNeed": {
      "baseline": 480,
      "actual": 480,
      "feedback": "NO_CHANGE_NO_ADJUSTMENTS"
    }
  },
  "avgSleepStress": 19.0,
  "sleepLevels": [ /* Sleep stage transitions */ ],
  "breathingDisruptionData": [ /* Breathing data */ ],
  "hrvData": [ /* HRV readings during sleep */ ],
  "sleepBodyBattery": [ /* Body Battery readings during sleep */ ]
}
```
- Comprehensive sleep data tracking duration and quality
- Breaks down sleep stages (deep, light, REM, awake) in seconds
- Includes sleep scores and personalized insights
- Tracks physiological measurements during sleep

### SpO2 (Blood Oxygen)
- Blood oxygen readings with timestamps
- Includes average, lowest and highest values
- May include continuous monitoring data during sleep

### Stress
```json
{
  "avgStressLevel": 32,
  "maxStressLevel": 75,
  "stressValuesArray": [
    [1746050400000, -2],  /* Timestamp, stress value */
    /* More stress values... */
  ],
  "calendarDate": "2025-05-01",
  "startTimestampGMT": 1746050400000,
  "endTimestampGMT": 1746136799999,
  "bodyBatteryValuesArray": [ /* Body Battery readings */ ]
}
```
- Stress levels throughout the day
- Records average and maximum stress values
- Minute-by-minute stress readings with timestamps

### Respiration
- Breathing rate data throughout the day
- Includes average, highest, and lowest values
- May include specialized metrics during sleep

## Physical Measurements

### Hydration
- Fluid intake tracking with timestamps
- Records daily hydration goals and achievements
- May include sweat loss estimates from activities

### Fitness Age
```json
{
  "chronologicalAge": 26,
  "fitnessAge": 19.28,
  "achievableFitnessAge": 18.0,
  "previousFitnessAge": 20.27,
  "components": {
    "vigorousDaysAvg": {
      "value": 2.8,
      "targetValue": 3,
      "potentialAge": 21.31,
      "priority": 2
    },
    "rhr": {
      "value": 47
    },
    "vigorousMinutesAvg": {
      "value": 93.6
    },
    "bmi": {
      "value": 24.6,
      "targetValue": 20.7,
      "improvementValue": 3.9,
      "potentialAge": 18.0,
      "priority": 1
    }
  },
  "lastUpdated": "2025-05-01T00:00:00.0"
}
```
- Calculated fitness age compared to chronological age
- Includes component factors that contribute to fitness age
- Provides target values and potential improvements

### Personal Records
- Performance benchmarks across activities
- Includes timestamps when records were achieved
- Categorized by activity type and measurement

## Device Data

### User Devices
- Detailed information about Garmin devices:
```json
{
  "deviceId": 3450916998,
  "displayName": "...",
  "primaryActivityTrackerIndicator": true,
  "manufacturer": "GARMIN",
  "productSku": "...",
  "currentFirmwareVersion": "...",
  "hasOpticalHeartRate": true,
  "solarChargeCapable": true,
  /* Hundreds of capability flags... */
}
```
- Includes extensive capability flags
- Records firmware versions and device types
- Identifies primary tracking devices

### Device Solar Data
```json
{
  "3450916998": {
    "solarDailyDataDTOs": [
      {
        "localConnectDate": "2025-05-01",
        "deviceId": 3450916998,
        "solarInputReadings": [
          {
            "readingTimestampLocal": "2025-05-01T00:01:00.0",
            "readingTimestampGmt": "2025-04-30T22:01:00.0",
            "solarUtilization": 0.0,
            "notChargingTooHot": false,
            "notChargingTooCold": false,
            "notChargingBatteryFull": false,
            "notChargingExternalPower": false,
            "notChargingUserDisabled": false,
            "notChargingOther": true,
            "activityTimeGainMs": 0,
            "charging": false
          },
          /* More solar readings... */
        ],
        "totalActivityTimeGainedMs": 437342
      }
    ]
  }
}
```
- For solar-powered devices
- Minute-by-minute solar charging data
- Records charging status and reasons for not charging
- Tracks activity time gained from solar power

## Data Analysis Applications

This rich dataset enables various types of health and fitness analysis:

1. **Sleep Pattern Analysis:** Track sleep quality, stages, and consistency over time
2. **Activity Tracking:** Monitor exercise frequency, intensity, and variety
3. **Stress Management:** Analyze stress patterns and their relationship to activities and sleep
4. **Heart Health Monitoring:** Track HRV, resting heart rate, and other cardiovascular metrics
5. **Fitness Progress:** Follow changes in fitness age and contributing factors
6. **Device Performance Analysis:** For solar-powered devices, analyze solar charging efficiency

## Technical Notes

- Timestamps are provided in both local time and GMT
- Many metrics include both summary values and detailed time-series data
- Metrics often include calculated insights and feedback messages
- Most numeric values use floating-point representation for precision
- Arrays are often used to represent time-series data with paired timestamp and value elements