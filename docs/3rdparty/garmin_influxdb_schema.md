=== DATABASE: GarminStats ===
=== MEASUREMENTS (TABLES) ===
name: measurements
name
----
ActivityGPS
ActivityLap
ActivitySession
ActivitySummary
BodyBatteryIntraday
BodyComposition
BreathingRateIntraday
DailyStats
DemoPoint
DeviceSync
HRV_Intraday
HeartRateIntraday
RacePredictions
SleepIntraday
SleepSummary
StepsIntraday
StressIntraday
VO2_Max
=== TAG KEYS (INDEXED COLUMNS) ===
name: ActivityGPS
tagKey
------
ActivityID
ActivitySelector
Database_Name
Device

name: ActivityLap
tagKey
------
ActivityID
ActivitySelector
Database_Name
Device

name: ActivitySession
tagKey
------
ActivityID
ActivitySelector
Database_Name
Device

name: ActivitySummary
tagKey
------
ActivityID
ActivitySelector
Database_Name
Device

name: BodyBatteryIntraday
tagKey
------
Database_Name
Device

name: BodyComposition
tagKey
------
Database_Name
Device
Frequency
SourceType

name: BreathingRateIntraday
tagKey
------
Database_Name
Device

name: DailyStats
tagKey
------
Database_Name
Device

name: DemoPoint
tagKey
------
DemoTag

name: DeviceSync
tagKey
------
Database_Name
Device

name: HRV_Intraday
tagKey
------
Database_Name
Device

name: HeartRateIntraday
tagKey
------
Database_Name
Device

name: RacePredictions
tagKey
------
Database_Name
Device

name: SleepIntraday
tagKey
------
Database_Name
Device

name: SleepSummary
tagKey
------
Database_Name
Device

name: StepsIntraday
tagKey
------
Database_Name
Device

name: StressIntraday
tagKey
------
Database_Name
Device

name: VO2_Max
tagKey
------
Database_Name
Device
=== FIELD KEYS (DATA COLUMNS) ===
name: ActivityGPS
fieldKey           fieldType
--------           ---------
ActivityName       string
Activity_ID        integer
Altitude           float
Cadence            integer
Distance           float
DurationSeconds    float
Fractional_Cadence float
HeartRate          float
Latitude           float
Longitude          float
Speed              float
Temperature        integer

name: ActivityLap
fieldKey        fieldType
--------        ---------
ActivityName    string
Activity_ID     integer
Avg_Cadence     integer
Avg_HR          integer
Avg_Speed       float
Avg_Temperature integer
Calories        integer
Cycles          integer
Distance        float
Elapsed_Time    float
Index           integer
Max_HR          integer
Max_Speed       float
Moving_Duration float
Sport           string

name: ActivitySession
fieldKey           fieldType
--------           ---------
ActivityName       string
Activity_ID        integer
Aerobic_Training   float
Anaerobic_Training float
Index              integer
Lengths            integer
Sport              string
Sub_Sport          string

name: ActivitySummary
fieldKey        fieldType
--------        ---------
Activity_ID     integer
Device_ID       integer
activityName    string
activityType    string
averageHR       float
averageSpeed    float
bmrCalories     float
calories        float
distance        float
elapsedDuration float
hrTimeInZone_1  float
hrTimeInZone_2  float
hrTimeInZone_3  float
hrTimeInZone_4  float
hrTimeInZone_5  float
lapCount        integer
locationName    string
maxHR           float
maxSpeed        float
movingDuration  float

name: BodyBatteryIntraday
fieldKey         fieldType
--------         ---------
BodyBatteryLevel integer

name: BodyComposition
fieldKey fieldType
-------- ---------
weight   float

name: BreathingRateIntraday
fieldKey      fieldType
--------      ---------
BreathingRate float

name: DailyStats
fieldKey                      fieldType
--------                      ---------
activeKilocalories            float
activeSeconds                 integer
activityStressDuration        integer
activityStressPercentage      float
averageSpo2                   float
bmrKilocalories               float
bodyBatteryAtWakeTime         integer
bodyBatteryChargedValue       integer
bodyBatteryDrainedValue       integer
bodyBatteryDuringSleep        integer
bodyBatteryHighestValue       integer
bodyBatteryLowestValue        integer
floorsAscended                float
floorsAscendedInMeters        float
floorsDescended               float
floorsDescendedInMeters       float
highStressDuration            integer
highStressPercentage          float
highlyActiveSeconds           integer
lowStressDuration             integer
lowStressPercentage           float
lowestSpo2                    integer
maxAvgHeartRate               integer
maxHeartRate                  integer
mediumStressDuration          integer
mediumStressPercentage        float
minAvgHeartRate               integer
minHeartRate                  integer
moderateIntensityMinutes      integer
restStressDuration            integer
restStressPercentage          float
restingHeartRate              integer
sedentarySeconds              integer
sleepingSeconds               integer
stressDuration                integer
stressPercentage              float
totalDistanceMeters           integer
totalSteps                    integer
totalStressDuration           integer
uncategorizedStressDuration   integer
uncategorizedStressPercentage float
vigorousIntensityMinutes      integer

name: DemoPoint
fieldKey  fieldType
--------  ---------
DemoField integer

name: DeviceSync
fieldKey    fieldType
--------    ---------
Device_Name string
imageUrl    string

name: HRV_Intraday
fieldKey fieldType
-------- ---------
hrvValue integer

name: HeartRateIntraday
fieldKey  fieldType
--------  ---------
HeartRate integer

name: RacePredictions
fieldKey         fieldType
--------         ---------
time10K          integer
time5K           integer
timeHalfMarathon integer
timeMarathon     integer

name: SleepIntraday
fieldKey                     fieldType
--------                     ---------
SleepMovementActivityLevel   float
SleepMovementActivitySeconds integer
SleepStageLevel              float
SleepStageSeconds            integer
bodyBattery                  integer
heartRate                    integer
hrvData                      float
respirationValue             float
sleepRestlessValue           integer
spo2Reading                  integer
stressValue                  integer

name: SleepSummary
fieldKey                fieldType
--------                ---------
averageRespirationValue float
averageSpO2Value        float
avgOvernightHrv         float
avgSleepStress          float
awakeCount              integer
awakeSleepSeconds       integer
bodyBatteryChange       integer
deepSleepSeconds        integer
highestRespirationValue float
highestSpO2Value        integer
lightSleepSeconds       integer
lowestRespirationValue  float
lowestSpO2Value         integer
remSleepSeconds         integer
restingHeartRate        integer
restlessMomentsCount    integer
sleepScore              integer
sleepTimeSeconds        integer

name: StepsIntraday
fieldKey   fieldType
--------   ---------
StepsCount integer

name: StressIntraday
fieldKey    fieldType
--------    ---------
stressLevel integer

name: VO2_Max
fieldKey      fieldType
--------      ---------
VO2_max_value float
