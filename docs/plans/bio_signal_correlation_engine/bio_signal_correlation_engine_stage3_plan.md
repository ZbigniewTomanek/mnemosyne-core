# Bio-Signal Correlation Engine – Stage 3 Plan (Activity Impact Variance)

## Objectives
- Quantify how consistently activities/meetings with the same title impact each bio-signal compared to a rolling historical baseline.
- Persist variance-focused metrics so downstream surfaces can track stability, emerging trends, and outliers.
- Extend the scheduled correlation task to summarise notable variance findings in the Telegram notification without disrupting Stage 1/2 behaviours.

## Scope & Assumptions
- Baseline is computed over a configurable sliding window of the past **N days** (per-user, default TBD) across all historical occurrences of a normalised event title.
- Both triggered and non-triggered metric evaluations contribute to the variance model so the distribution captures neutral and significant effects alike.
- Variance is tracked **per bio-signal** (`BioSignalType`) to avoid over-aggregating heterogeneous metrics.
- The latest correlation run provides the “current effect” to compare against the historical baseline distribution.

## Data Inputs & Normalisation
- Source events: `CorrelationRunSummary.results` containing `EventCorrelationResult` with evaluated metrics.
- Historical context: records stored via `DBService.fetch_correlation_events` filtered by lookback window, including triggered `CorrelationMetricRecord`s and persisted metadata (`categories`, `metadata`).
- Event grouping key: normalised version of `event.title` (lowercase + trimmed + optional slug). Consider augmenting with optional disambiguators (e.g., `source`, calendar ID) if collisions appear.
- Metrics considered: all `MetricEffect` entries (triggered + evaluated) mapped by `metric` enum. Sleep analysis notes remain available via `notes` if needed for reporting.

## Computation Flow
1. **Extraction** – During a run, construct `EvaluatedMetricSnapshot` objects capturing: event id/title/source, metric type, effect size, confidence, timestamp, metadata references.
2. **Historical Fetch** – Variance service requests prior snapshots for the same title + metric within the configured day window via new DB accessors.
3. **Baseline Stats** – Compute baseline mean, variance, standard deviation, and sample count over historical effect sizes. Skip calculation if below minimum sample threshold (configurable, default ≥3).
4. **Current Delta** – Compare the latest effect size against baseline mean. Derive:
   - Absolute delta (`current - mean`).
   - Normalised score (z-score-esque: `delta / max(stddev, epsilon)`), falling back to MAD when stddev ≈0.
   - Trend direction (increase/decrease/neutral) using `_EFFECT_SIZE_EPSILON` for consistency.
5. **Aggregate Result** – Produce `ActivityImpactVariance` domain objects with metadata: window bounds, sample count, baseline stats, current observation, change score, and supporting notes.

## Persistence Model
- **New table**: `correlation_activity_variance`
  - Columns: `id` (UUID), `run_id`, `event_id`, `title_key`, `raw_title`, `metric`, `window_start`, `window_end`, `baseline_mean`, `baseline_stddev`, `baseline_sample_count`, `current_effect`, `delta`, `normalised_score`, `trend`, `metadata_json`, `created_at`, `config_hash`.
- **DBService extensions**:
  - `add_activity_variance(ActivityImpactVarianceEntry)` for inserts.
  - `fetch_metric_history(title_key, metric, window_start)` to support baseline computation without exposing SQL calls elsewhere.
  - Store a deterministic `config_hash` per variance to short-circuit duplicate calculations when the same event is reprocessed with identical settings.
- Backfill/migration: ensure `_initialize_tables` adds the new table & columns idempotently. Consider index on `(title_key, metric, created_at)` for lookups.

## Services & Responsibilities
- `ActivityImpactVarianceService`
  - Dependencies: `DBService`, optional clock abstraction for testability.
  - Methods:
    - `prepare(run_request)` to prefetch historical windows if batching helps.
    - `compute_variances(run_summary)` returns list of variance results for all events in the run.
    - `_normalise_title`, `_build_window_bounds`, `_calculate_baseline_stats`, `_score_delta` as private helpers to keep logic isolated & unit-testable.
  - Applies SRP by owning the variance logic separate from `CorrelationEngine` core metric evaluation.
- `CorrelationEngine`
  - Inject optional variance service. After per-event processing, pass the summary to variance service which persists results (either inside service or via returned entries handled in `_persist_results`).
  - Extend `_persist_results_sync` to store variance entries if provided, reusing async-to-thread pattern to avoid blocking the event loop.

## Scheduler & Notifications
- `CorrelationEngineTask`
  - After calling `job_runner.run()`, request variance results from the service.
  - Summarise notable deviations (e.g., absolute delta above threshold or |normalised_score| ≥ config).
  - Enhance Telegram message with a concise section (e.g., “📈 Variance alerts”) listing up to N titles with metric + score.
  - Guard against empty variance results to avoid noisy notifications.

## Configuration Additions (`CorrelationEngineConfig`)
- `variance_analysis` section (new Pydantic model):
  - `enabled: bool = True`
  - `lookback_days: int` (defaults 30?)
  - `min_samples: int`
  - `min_score_for_alert: float`
  - `max_alerts: int`
  - `title_normalizer: Literal["lower_trim", "slug"]` (optional for future flexibility).
- Ensure `to_job_config()` propagates variance settings to runtime services without coupling.

## Implementation Steps
1. **Models & Config** – Add `VarianceAnalysisConfig`, `ActivityImpactVariance` models, update config parsing, and extend `CorrelationJobConfig` to include variance settings.
2. **DB Migration** – Update `DBService` table creation & helper methods; write small regression tests for new methods.
3. **Domain Service** – Implement `ActivityImpactVarianceService` with unit tests covering edge cases (no history, zero variance, mixed directions).
4. **Engine Integration** – Inject the new service via factory. After run persistence, compute and store variance entries, respecting async execution patterns.
5. **Scheduler Update** – Modify `CorrelationEngineTask` notification builder to include variance summaries; add formatting helpers for readability.
6. **Telemetry & Logging** – Log counts (events analysed, baselines skipped) and emit structured telemetry to `CorrelationRunSummary.telemetry` for observability.
7. **Documentation & Config Samples** – Update README/config docs with new options and usage examples.

## Testing Strategy
- Unit tests for title normalisation, baseline stat calculation, and scoring logic using synthetic histories.
- Integration-style test stub invoking service against an in-memory SQLite DB to verify persistence and retrieval.
- Contract test for scheduler message formatting given mock variance results.

## Risks & Mitigations
- **Sparse history** – Provide graceful fallbacks (skip or mark insufficient data) to avoid misleading variance.
- **Title collisions** – Log potential collisions, consider enriching key with source metadata if needed.
- **Performance** – Fetch history in batch per run to minimise DB round-trips; sliding window keeps dataset bounded.
