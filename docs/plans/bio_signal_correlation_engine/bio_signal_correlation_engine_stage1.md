# Bio-Signal Correlation Engine – Stage 1 Architecture

## Context

Stage 1 delivers an automated pipeline that links calendared events to short-term physiological responses measured by Garmin devices. The objective is to establish reproducible, statistically grounded correlations across stress, body battery, heart rate, breathing rate, and sleep. The engine uses existing services—calendar ingestion, InfluxDB exports, scheduler orchestration, and SQLite persistence—to run unattended and persist outputs for later reporting layers (Obsidian/Telegram).

## Architectural Overview

- **Event Source (`CalendarEventSource`)**
  - Wraps `CalendarService` to emit normalized `CorrelationEvent` objects.
  - Respects lookback windows and calendar filters, tags events with calendar names, and enriches metadata (location/notes).

- **Metric Source (`InfluxMetricSource`)**
  - Uses `InfluxDBGarminDataExporter` to pull intraday Garmin CSVs once per run.
  - Normalizes metric-specific frames and resamples/interpolates series to a configurable frequency.

- **Correlation Engine (`CorrelationEngine`)**
  - For each event/metric pair, aligns baseline/post windows, runs Welch’s t-test (SciPy-supported when available), and evaluates thresholds for effect size, confidence, and sample count.
  - Persists run/event/metric outcomes via `DBService` and optionally notifies publishers.

- **Scheduled Task (`CorrelationEngineTask`)**
  - Registers an async job with `ScheduledTaskService` using cron defined in `BotSettings.correlation_engine`.
  - Each invocation pulls events, preloads metrics, executes the engine, and records results.

- **Service Wiring (`ServiceFactory`)**
  - Exposes correlation-specific dependencies (event source, metric source, engine, job runner) using cached properties, so the rest of the bot can construct and schedule the job easily.

## Key Decisions

1. **Statistical Significance (Welch’s t-test)**
   - Adopted Welch’s t-test for unequal variances/samples with a normal approximation fallback when SciPy is unavailable. Returns p-values and confidence for filtering.

2. **Generic Event Contract**
   - `CorrelationEvent` accepts multiple sources (`calendar`, `obsidian`, `garmin_activity`, `manual`) preparing the pipeline for future Stage 2 inputs without refactoring.

3. **Config-Driven Thresholds**
   - `CorrelationEngineConfig` in `BotSettings` defines cron cadence, window sizes, and per-metric thresholds, allowing adjustment without code changes.

4. **Persistence Strategy**
   - Leveraged `DBService` (SQLite) with new tables `correlation_runs`, `correlation_events`, `correlation_metric_effects` for structured storage and historical analysis.

5. **Preparation Hook**
   - `MetricSource.prepare` allows one-shot loading/caching of data (Influx export) before per-event evaluation to minimize redundant I/O.

## Component Map

| Layer | Components | Responsibility |
|-------|------------|----------------|
| Input | `CalendarService`, `CalendarEventSource` | Fetch and normalize events in lookback window |
| Data | `InfluxDBGarminDataExporter`, `InfluxMetricSource` | Export Garmin intraday data, resample, provide metric slices |
| Core | `CorrelationEngine`, `WelchTTest` | Align windows, run statistical tests, apply thresholds |
| Persistence | `DBService` (correlation tables) | Store run metadata, event details, metric effects |
| Scheduling | `CorrelationEngineTask`, `ScheduledTaskService` | Cron-based execution |
| Manual Ops | `tests/scripts/run_correlation_engine.py` | On-demand testing/inspection |

## Usage Flow

1. Scheduler triggers the correlation job on the configured cron.
2. `CorrelationJobRunner` requests events via `CalendarEventSource`.
3. `InfluxMetricSource.prepare` loads Garmin datasets.
4. `CorrelationEngine` evaluates each event/metric combination with Welch’s t-test and persists significant findings.
5. Results are stored in SQLite and logged; reporting layers can later consume these tables.

## Future Work

- Add Obsidian/Telegram publishers to surface insights.
- Support additional event sources (Obsidian notes, manual annotations).
- Enhance statistical analysis with non-parametric tests (Mann–Whitney U) and effect-size tracking across runs.
