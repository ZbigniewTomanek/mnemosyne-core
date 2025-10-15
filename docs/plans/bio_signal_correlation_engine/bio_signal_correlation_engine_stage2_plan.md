# Bio-Signal Correlation Engine – Stage 2 Plan (Garmin Activities + Sleep Impact)

## Objectives
- Enrich correlation runs with Garmin activity events alongside calendar events.
- Track how intense activities and scheduled events influence subsequent sleep quality and recovery markers.
- Provide configuration hooks and sensible defaults so Stage 2 can be toggled per source or metric without destabilising Stage 1 behaviour.

## Data Inputs & Normalisation

### Garmin Activity Events
- Pull from `GarminExportData.activity_summary` as the primary table.
- Merge optional enrichments:
  - `activity_session` for `Aerobic_Training`, `Anaerobic_Training`, `Sport`, `Sub_Sport`.
  - `activity_lap` for granularity (optional, only needed when calculating intra-activity variability).
- Required columns per event:
  - Identifiers: `Activity_ID`, `time` (`measurement` timestamp), `activityType`, `activityName`.
  - Load metrics: `elapsedDuration`, `movingDuration`, `distance`, `calories`, `averageHR`, `maxHR`.
  - Intensity: sum of `hrTimeInZone_4`, `hrTimeInZone_5`.
  - Context: `locationName` when present.
- Default filters for emitting `CorrelationEvent` (`source="garmin_activity"`):
  - `min_duration_minutes = 20`.
  - `movingDuration / elapsedDuration >= 0.5`.
  - `hrTimeInZone_4 + hrTimeInZone_5 >= 300` seconds.
  - Include all sports unless `exclude_sports` is set; expose optional `include_sports` allow-list.
- Generated metadata keys: `activityType`, `activityName`, `distance`, `elapsedDuration`, `movingDuration`, `calories`, `averageHR`, `maxHR`, `hrZone4Seconds`, `hrZone5Seconds`, `Aerobic_Training`, `Anaerobic_Training`, `Sport`, `Sub_Sport`, `locationName`.

### Calendar Events (Stage 1 baseline)
- Keep existing behaviour; allow opt-out per calendar through configuration.

### Sleep Observations
- Use `GarminExportData.sleep_summary` for nightly aggregates:
  - `sleepScore`, `sleepTimeSeconds`, `deepSleepSeconds`, `remSleepSeconds`, `avgOvernightHrv`, `avgSleepStress`, `bodyBatteryChange`, `restingHeartRate`.
- When minute-level traces are required, fall back to `sleep_intraday` (stages, respiration, stress) but only within the matched sleep window to avoid unnecessary load.
- Capture baseline context via `daily_stats` when computing deltas (e.g., `bodyBatteryAtWakeTime`, `restingHeartRate`, `stressDuration`).

## Job Runner & Metrics
- Update `CorrelationJobRunner` to accept multiple `EventSource` instances. Merge, de-duplicate (by `id`), sort by `start`.
- Introduce `GarminActivityEventSource` reusing `InfluxDBGarminDataExporter` output. Hook into `ServiceFactory` so exporter is shared with metric source caching.
- Maintain existing metric evaluation flow; sleep analysis extends it with a specialised window strategy (see below).

## Sleep Correlation Strategy
- For non-sleep metrics (stress, HR, body battery, breathing rate) continue using Stage 1 windows.
- For sleep impact:
  - Pair each event with the first qualifying sleep session ending within `lookahead_hours` (default 36 h).
  - Baseline = rolling stats from the preceding `baseline_nights` (default 5).
  - Effect window = matched sleep session; treat `sample_count` as the number of aggregate metrics involved (e.g., 1-2) and relax minimum-sample thresholds accordingly.
  - Compute deltas on `sleepScore`, `sleepTimeSeconds`, `deepSleepSeconds`, `avgOvernightHrv`, `avgSleepStress`, `bodyBatteryChange`, `restingHeartRate`.
  - When Welch’s t-test is not meaningful (very small N), fall back to a heuristic confidence: scaled by deviation vs. baseline standard deviation or interquartile range.

## Configuration Layout (defaults)
Embed in `telegram_bot/config.py`:

```python
class GarminActivitySourceConfig(BaseModel):
    enabled: bool = True
    min_duration_minutes: int = 20
    min_moving_ratio: float = 0.5
    min_hr_zone45_seconds: int = 300
    include_sports: set[str] | None = None
    exclude_sports: set[str] | None = None
    metadata_fields: list[str] = Field(
        default_factory=lambda: [
            "activityType",
            "activityName",
            "distance",
            "elapsedDuration",
            "movingDuration",
            "calories",
            "averageHR",
            "maxHR",
            "hrZone4Seconds",
            "hrZone5Seconds",
            "Aerobic_Training",
            "Anaerobic_Training",
            "Sport",
            "Sub_Sport",
            "locationName",
        ]
    )

class CalendarEventSourceConfig(BaseModel):
    enabled: bool = True
    calendar_filters: list[str] | None = None

class CorrelationSourcesConfig(BaseModel):
    calendar: CalendarEventSourceConfig = Field(default_factory=CalendarEventSourceConfig)
    garmin_activity: GarminActivitySourceConfig = Field(default_factory=GarminActivitySourceConfig)

class SleepCorrelationConfig(BaseModel):
    enabled: bool = True
    baseline_nights: int = 5
    lookahead_hours: int = 36
    main_sleep_only: bool = True
    min_sleep_duration_minutes: int = 240
    metrics: dict[BioSignalType, MetricThreshold] = Field(
        default_factory=lambda: {
            BioSignalType.SLEEP: MetricThreshold(min_delta=15.0, min_samples=2, min_confidence=0.9),
            BioSignalType.BODY_BATTERY: MetricThreshold(min_delta=10.0, min_samples=2, min_confidence=0.85),
        }
    )

class CorrelationEngineConfig(BaseModel):
    enabled: bool = True
    cron: str = "0 2 * * *"
    lookback_days: int = 7
    timezone: str | None = None
    window: WindowConfig = Field(default_factory=WindowConfig)
    sources: CorrelationSourcesConfig = Field(default_factory=CorrelationSourcesConfig)
    metrics: dict[BioSignalType, CorrelationMetricConfig] = Field(default_factory=_default_metric_config)
    sleep_analysis: SleepCorrelationConfig = Field(default_factory=SleepCorrelationConfig)
```

## Implementation Steps
1. **Sources** – build `GarminActivityEventSource`, wire into `CorrelationJobRunner` and `ServiceFactory`, share exporter cache.
2. **Configuration** – add classes above, extend env parsing if needed, update docs on altering thresholds.
3. **Job Runner Update** – accept multiple sources, merge event lists, record per-source counts in telemetry.
4. **Sleep Pairing** – add helper in metric source or new sleep service to map events -> sleep sessions, compute baseline stats.
5. **Engine Enhancements** – support per-metric window overrides for sleep analysis, fallback scoring when Welch t-test is not applicable.
6. **Persistence & Reporting** – extend DB writes to include source metadata (activity specifics, matched sleep identifiers) and update reporting scripts.
7. **Testing** – unit tests for new source filters, sleep pairing logic, configuration parsing; integration test via `tests/scripts/run_correlation_engine.py` scenario using mocked exporter outputs.

## Reasonable Defaults Summary
- Activity threshold: 20 min duration, 50% moving ratio, >=5 min in HR zones 4–5.
- Sleep pairing window: first main sleep within 36 h, compare against previous 5 nights.
- Sleep metric thresholds: `ΔsleepScore >= 15`, `ΔbodyBattery >= 10` with relaxed sample requirements.
- Sources enabled by default but independently controllable via config.

These defaults should surface significant training loads and their sleep effects without overwhelming the correlation engine with noise from casual movement or naps. Adjust numeric thresholds after observing real-world distributions.
