# AI Assistant Life Context Tool Plan

## Current Context Flow Findings
- `MorningReportService` orchestrates Garmin export, Obsidian daily notes, calendar events, and correlation insights, then hand-builds an XML-style prompt. The fetching logic is tightly coupled to prompt formatting, making reuse difficult.
- `ContextAggregator` (smart triggers) repeats similar fetching steps with its own markdown formatter, again directly calling `ObsidianService`, `InfluxDBGarminDataExporter`, `CalendarService`, and `DBService`.
- `AIAssistantService` currently injects only correlation summaries plus recent chat turns ahead of the user query; the assistant has no tool to request richer life context on demand.
- Variance insights (`ActivityImpactVariance`) are computed and stored by the correlation engine, but there is no read API or formatter that exposes “important variance changes” to prompts.
- Shared helpers exist for Garmin day formatting (`format_garmin_day_markdown_md`, `format_current_sleep_status_md`) and correlation events (`format_correlation_events`), yet there is no cohesive abstraction that wraps data extraction + presentation for multiple surfaces.

## Requirements Recap
- Introduce an AI-assistant tool `fetch_context(start_date, end_date=today, metrics="all")` that returns the user’s life context for the requested window.
- The tool must surface: (1) daily notes, (2) Garmin summaries, (3) calendar meetings & reminders, (4) correlation events, (5) notable variance shifts (e.g., high |normalised_score|).
- Date arguments should accept ISO `YYYY-MM-DD` strings (or optional datetime) with sensible defaults (end = today, start fallback configurable lookback).
- `metrics` parameter should allow filtering (e.g., list of `"notes"`, `"garmin"`, `"calendar"`, `"correlations"`, `"variance"`), with `"all"` as default.
- Returned payload must be LLM-friendly (structured markdown or JSON) and token-aware, with per-section limits (e.g., top-N notes/events, summarised Garmin data).
- Purpose: allow the agent to answer questions like “How was my health last month?” without hardcoding context prefaces.
- Prompt formatting across consumers (morning report, smart triggers, assistant tool) needs to include variance info in a consistent way once available.

## Proposed Architecture

### 1. Shared Context Module (`telegram_bot/service/life_context/`)
- **LifeContextRequest** (Pydantic): `start_date`, `end_date`, `metrics: set[LifeContextMetric]`, `max_token_budget` override.
- **LifeContextBundle** (dataclass): structured result with optional sections (`notes_by_date`, `garmin`, `calendar`, `correlations`, `variance`, `persistent_memory`) storing raw domain payloads.
- **LifeContextFetcher**: orchestrates data retrieval from existing services (Obsidian, Garmin exporter, Calendar, DB) using async methods. Responsibilities split per metric (SOLID: single responsibility per method, fetcher isolated from formatting).
- **LifeContextFormatter**: converts `LifeContextBundle` to markdown/JSON sections; provides token-budget guardrails and returns an explicit error if the estimate exceeds the configured budget.
- Module exposes async facade `LifeContextService.build_context(request: LifeContextRequest) -> LifeContextFormattedResponse` returning both the structured bundle and the rendered string (so different consumers can choose representation).

### 2. Data Access Enhancements
- **ObsidianService** ✅ `get_daily_notes_between(start_date, end_date, max_notes)` returns newest-first notes across current + archive folders with graceful skips.
- **InfluxDBGarminDataExporter** ➡️ wrapped by `GarminContextService.get_window(start_date, end_date)` to refresh once and calculate `days = (end_date - start_date) + 1`.
- **DBService** ✅ `fetch_activity_variances(start_date, end_date, limit, min_score)` returns entries ordered by `|normalised_score|`.
- **CalendarService** ✅ `get_events_between(start_date, end_date, limit, include_all_day, include_reminders)` trims results as needed.

### 3. Formatting Extensions
- ✅ Reuse existing Garmin markdown helpers; add summariser that collapses multi-day data into concise bullet list when window >1 day.
- ✅ Extend `format_correlation_events` (or wrapper) to honour `limit` and annotate variance overlap when available.
- ✅ Create `format_activity_variances(variances: Sequence[ActivityImpactVariance], tz)` returning markdown keyed by event title + metric, highlighting baseline vs current effect, z-score, and trend.
- Update morning-report prompt builder and smart-context aggregator to pull variance section via the new formatter for consistency. *(pending once downstream refactors land)*

### 4. AI Tool Integration
- Implement async tool function `async def fetch_context(start_date: str, end_date: str | None = None, metrics: str | list[str] = "all") -> dict[str, Any]`.
  - Parse inputs into `LifeContextRequest` (default start: end - default window from config, e.g., 7 days).
  - Call shared builder; return structured JSON with `sections` and `rendered_markdown` so the LLM can inspect raw data or drop-in summary.
- Wrap with `function_tool` and register inside `get_ai_assistant_agent`; add friendly tool description for usage guidance.
- Update `AIAssistantConfig.ai_assistant_instructions` to mention the new tool and give examples (e.g., “fetch_context(start_date="2024-05-01", metrics=["garmin","variance"])”).
- ✅ Wire tool + instruction updates. Continue monitoring `AIAssistantService` preamble behaviour to avoid redundant context now that the tool is available.

### 5. Adoption in Existing Surfaces & Tasks
- **[PENDING]** Refactor `MorningReportService` to request `LifeContextBundle` instead of reimplementing fetch logic. Custom prompt builder can still create XML but should read from bundle/formatter (supporting dependency inversion via injected formatter interface).
- ✅ Refactor `ContextAggregator.gather_context` to use the shared builder with appropriate metrics subset; reduces duplicate logic and ensures variance inclusion.
- ✅ Wire `SmartContextTriggerTask` (and its `ContextTriggerExecutor`) to obtain the aggregator via the shared facade, avoiding bespoke data assembly.
- **[PENDING]** Extend `MemoryConsolidationTask` to reuse `LifeContextFetcher` (via the shared aggregator) when gathering weekly notes/log context, replacing direct Obsidian file loops (currently at lines 261-274) while keeping existing LLM prompts intact.
- Ensure all consumers can request the raw bundle for bespoke ordering (e.g., morning report's XML per-date sections) while still benefiting from centralised fetching.

### 6. Configuration & Defaults
- Extend `BotSettings` with `life_context` defaults (lookback days, token budget, section limits) and surface an easy entry point via `ServiceFactory.life_context_service`.
- Provide sensible section limits (e.g., max 5 notes, top 5 calendar events, top 5 correlations, top 3 variance alerts) configurable via settings/constants. *(section limits still to be finalised)*
- Guarantee timezone awareness (use `BotSettings.tz` for formatting and default date computations). ✅ Life context service is constructed with `bot_settings.tz`.

## Progress Update
- Implemented the life-context module (`LifeContextMetric`, request/bundle models, fetcher, formatter, service facade) with token-budget enforcement and async metric-specific fetching.
- Added data-service capabilities required by the fetcher: Obsidian range access, DB variance retrieval, calendar range helper, and a Garmin window wrapper.
- Hooked the new service into application configuration (`BotSettings.life_context`) and the `ServiceFactory`, making the shared context builder available to future consumers.
- Extended Garmin daily metrics collection to degrade gracefully on unexpected API errors instead of raising.
- Landed targeted test suites covering the new module and service adapters.
- Delivered the `fetch_context` tool with instruction updates so the assistant can pull life context on demand.

## Next Steps
- Refactor `MorningReportService` to request `LifeContextService` data (including persistent memory + variance) and adapt the XML builder to consume the shared bundle.
- Ensure smart-context scheduling remains aligned with the shared aggregator (complete for current triggers); monitor for additional trigger variants.
- **[PENDING]** Extend `MemoryConsolidationTask` to reuse the shared fetcher instead of bespoke Obsidian loops (currently still uses direct file reading in lines 261-274), keeping existing LLM prompts intact.
- Add targeted tests for the assistant tool entry point (parsing + schema) and end-to-end validation once surface refactors land.
- Document usage patterns and perform end-to-end manual QA after the remaining migrations.

## Implementation Steps
- [x] **Pydantic Models & Enums** – `LifeContextMetric`, request/response schemas, token-budget config.
- [x] **DBService Enhancements** – `fetch_activity_variances` implemented with tests.
- [x] **Obsidian Range Fetch** – `get_daily_notes_between` with archive coverage and tests.
- [x] **Context Fetcher** – Async fetcher/service built with fakes-based tests.
- [x] **Formatting Layer** – Formatter now reuses Garmin/correlation helpers and emits variance markdown.
- [x] **Shared Facade** – Service factory wiring and config defaults in place.
- [x] **Tool Function** – Assistant tool implemented, instructions updated, registered with the agent.
- [ ] **Surface Refactors** – Morning report and memory consolidation still consume bespoke logic; smart triggers **completed** and now use the shared life-context service; memory consolidation **pending** integration.
- [ ] **Documentation & Examples** – Update public docs once tool+surfaces are integrated.
- [ ] **Manual QA** – Execute end-to-end flows after refactors/tool rollout.

## Testing Strategy
- Unit tests for new DB accessor (SQLite in-memory) and Obsidian range fetcher (tmpdir fixtures).
- Fetcher tests with mock services ensuring metric filters behave and defaults respected.
- Formatter snapshot tests (pytest approval-style) to catch regressions in markdown output.
- Tool integration test invoking `fetch_context` via agent runner stub to ensure response schema matches expectations.
- Regression runs for morning report & context trigger to confirm outputs still render and include variance.

## Open Questions & Assumptions
- ✅ Desired maximum lookback is now configurable via `LifeContextConfig.default_lookback_days` (wired through `BotSettings.life_context`).
- ✅ Garmin data will be passed through as raw per-day markdown; any summarisation will be an optional formatter enhancement.
- ✅ Variance sections must include non-alert entries when explicitly requested; current DB fetch honours `min_score` but otherwise returns all matching rows ordered by score.
- Token budget handling returns a single structured response with explicit error once the configurable limit is exceeded – streaming remains out of scope for the initial tool.
