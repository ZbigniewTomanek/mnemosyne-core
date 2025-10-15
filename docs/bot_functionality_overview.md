# Telegram Bot & AI Assistant — Functionality Overview

This document describes the current functionality, architecture, and integrations of the Telegram bot in this repository, with a focus on the core AI assistant and surrounding services. It also highlights natural extension points for future features.

## High‑Level Capabilities

- Chat with an AI assistant (text and voice) that maintains conversational memory and can fetch contextual life summaries on demand.
- Capture structured notes into Obsidian daily notes with auto-tagging, semantic search, and correlation-aware insights.
- Run scheduled analytics (morning briefings, weekly memory consolidation, correlation engine, smart triggers) with Telegram delivery and manual overrides.
- Integrate Garmin, calendar, and Obsidian data to surface trends, variance alerts, and life-context exports.
- Execute AppleScript on macOS to control apps (Calendar, Notes, Mail, Safari, Reminders, Messages, etc.).
- Manage environment variables, bot logs, and scheduled jobs directly from Telegram.
- Log food and medications through guided conversations backed by the SQLite datastore.

---

## Architecture

- Entry point: `telegram_bot/main.py`
  - Builds `Application` (python-telegram-bot), configures handlers and commands.
  - Starts background workers and scheduled tasks; sends startup/shutdown DM to configured user.
- Dependency wiring: `telegram_bot/service_factory.py`
  - Lazily constructs services (DB, Garmin, Obsidian, AI assistant, Whisper, scheduler, etc.).
- Core services:
  - `AIAssistantService` — orchestrates the AI agent, context building, and message logging.
  - `MessageTranscriptionService` — transcribes voice using `faster-whisper` in a process pool.
  - `ObsidianService` — safe file I/O to an iCloud-backed Obsidian vault with locking and git sync.
  - `ObsidianDailyNotesManager` — LLM-assisted note cleanup/tagging and AI reflection logging.
  - `LifeContextService` — unifies calendar, Garmin, Obsidian notes, correlations, variance, and persistent memory into exportable bundles.
  - `ObsidianEmbeddingIndexer` — maintains a Chroma-backed semantic index for Obsidian Markdown files (CLI + scheduled refresh).
  - `CorrelationJobRunner` — coordinates correlation/variance analysis across Garmin and calendar sources.
  - `PersistentMemoryUpdater` — applies LLM-produced deltas to the long-term memory document with deterministic IDs and routing rules.
  - `ScheduledTaskService` — cron-like runner with optional background execution/callbacks.
  - `ScheduledJobsFacade` — exposes registered tasks for manual inspection and triggering via Telegram.
  - `BackgroundTaskExecutor` — async workers + `ProcessPoolExecutor` for CPU-bound tasks.
  - `LLMService` — thin wrapper for LangChain models with (async) structured outputs.
- AI agent stack: `telegram_bot/ai_assistant`
  - `AIAssistant` agent with tools and handoffs (Obsidian agent via MCP, AppleScript tool, WebSearch, product search agent).
  - Tracing to local filesystem via `LocalFilesystemTracingProcessor`.

---

## Bot Commands & Conversations

Defined in `telegram_bot/handlers` and registered in `main.py`. `PrivateHandler` gates commands to the configured owner; `PublicHandler` allows wider use (e.g. Garmin onboarding).

- **Context & Search**
  - `/export_context` — interactive flow to export life context (notes, Garmin metrics, correlations, variance, persistent memory) for a chosen date range and format (Markdown/JSON).
  - `/search_obsidian <query>` — run semantic search across the Obsidian vault using the embedding index with Markdown-formatted results and vault links.
  - `/scheduled_jobs` — browse registered cron jobs, inspect metadata, and trigger a job immediately from Telegram.
- **Health & Daily Logs**
  - `/log_food` → multi-step conversation capturing food item, macros, and comments into the SQLite log.
  - `/list_food [limit]` — list the latest food entries (default 10) with macro breakdown.
  - `/log_drug` → guided conversation that records medication name and dosage multipliers.
  - `/list_drugs [limit]` — show recent medication entries.
- **Garmin Integration**
  - `/connect_garmin` — email → password → optional MFA flow storing user tokens securely.
  - `/garmin_status` — report whether the current user is connected.
  - `/garmin_export` — interactive export builder with format (Markdown, aggregated JSON, raw JSON) and date range selection.
  - `/disconnect_garmin` — revoke Garmin tokens by purging the token directory.
- **Operations & Environment Management**
  - `/list_env` — list variable names detected in `.env` with line numbers.
  - `/read_env KEY` — print the value for a variable (with safety guard for large payloads).
  - `/set_env KEY VALUE` — insert or update entries in `.env`, including JSON string normalisation.
  - `/read_env_file KEY` — send the variable value as a file when it exceeds chat limits.
  - `/set_env_file KEY` — start a file-upload conversation that writes the uploaded value into `.env` (supports JSON validation).
  - `/get_logs [lines]` — send the tail of `out/log/debug.log` and request an LLM summary of the snippet.
  - `/restart` — reply with acknowledgement and invoke `BotRestartService.restart()`.
- **Utility**
  - `/cancel` — available in every conversation to abort the flow and clear state.

Message handlers:
- Text: `DefaultMessageHandler` routes free-form chat to `AIAssistantService.run_ai_assistant()`.
- Voice: `VoiceMessageHandler` downloads, transcribes with Whisper, echoes the transcript, and re-asks the assistant with a voice-specific prompt context.

---

## AI Assistant

- Service: `telegram_bot/service/ai_assitant_service.py`
  - On first use, builds the `AIAssistant` agent from config (`BotSettings.ai_assistant`).
  - Retrieves recent messages from `DBService` and prepends a compact context to the query.
  - Uses `agents.Runner.run(...)` with `max_turns` from config.
  - Cleans/normalizes output for Telegram (`utils.clean_ai_response`) and stores the message/response.

- Agent: `ai_assistant/agents/ai_assitant_agent.py`
  - Tools:
    - `log_daily_note` — wraps `ObsidianDailyNotesManager.log_daily_note` to append timestamped notes with smart tagging.
    - `fetch_context` — calls into `LifeContextService` to assemble configurable bundles (notes, Garmin, calendar, correlations, variance, persistent memory) for a requested date range.
    - `execute_applescript` — macOS automation via `/usr/bin/osascript` (Notes, Calendar, Mail, Finder, Safari, Reminders, Messages, etc.).
    - `semantic_search` — provided by `ai_assistant/tools/semantic_search_tool.py`, backed by `ObsidianEmbeddingIndexer` and the Chroma vector store; returns scored snippets.
    - `WebSearchTool` — pulls fresh information from the public web.
  - Handoffs:
    - `ObsidianAgent` — MCP filesystem agent for advanced vault editing/search beyond the lightweight semantic tool.
    - `PolishProductSearchAgent` — structured workflow for Polish e-commerce product research.
  - Instructions bias toward:
    - Default note capture to Obsidian for reflective or informational messages.
    - Delegation to Obsidian agent or semantic tool for vault questions.
    - Fetching life context before answering questions about health, schedule, or recent activity.
    - Using AppleScript for messaging/automation on trusted contacts without redundant confirmation.
    - Web/product search only when local context is insufficient.
  - Tracing: `LocalFilesystemTracingProcessor` writes agent traces to `out/log/ai_assistant_traces.log` for debugging.

- Output formatting: `utils.clean_ai_response(...)`
  - Handles strings and Pydantic outputs (e.g., product search results) for Telegram-friendly display.

---

## Voice Transcription

- `MessageTranscriptionService`
  - Runs `faster-whisper` in worker processes; configurable via `WhisperSettings` in `BotSettings`.
  - Returns segments and transcription info; handler sends transcript to chat, then forwards to AI assistant.
  - Voice inputs are wrapped in a “VOICE TRANSCRIPTION INPUT” context prompt to mitigate ASR errors.

---

## Obsidian Integration

- `ObsidianService`
  - Operates directly on iCloud-backed vault with:
    - Intra-process async locks (per-path),
    - Inter-process file locks (`fcntl`),
    - iCloud placeholder waiting, and
    - Optional pre-write `git fetch/checkout` of target files.
  - Helpers for daily note path, AI logs path, persistent memory file, and weekly memory path generation.

- `ObsidianDailyNotesManager`
  - `log_daily_note(note_content: str)` pipeline:
    1) Ensure today’s daily note exists or create minimal scaffold.
    2) Use an LLM (configurable) to lightly clean the text and generate 2–5 tags.
    3) Append timestamped note to “📖 Myśli przeróżne” section.
    4) Read the day’s note; prompt another LLM to generate a structured AI reflection.
    5) Append the reflection to the day’s AI log under `30 AI Assistant/memory/logs`.

- `ObsidianAgent` (MCP)
  - Starts an MCP filesystem server (via Docker) with the vault mounted for structured agent access.
  - Supports read/write/edit/list/search/get_file_info primitives.

- `ObsidianEmbeddingIndexer`
  - Uses recursive chunking and a Chroma vector store to index Markdown content with metadata (`relative_path`, checksum, mtime).
  - Powers `/search_obsidian`, the AI assistant `semantic_search` tool, and scheduled embedding refreshes.

---

## Garmin Integration

- Commands: auth, status, disconnect, export.
- Morning report consumes Garmin data (see below) for contiguous-day summaries, activities, stress, HR, Body Battery.
- Supporting services: `garmin_connect_service.py`, `influxdb_garmin_data_exporter.py`, and analysis helpers under `service/garmin_analysis`.

---

## Life Context & Correlation Engine

- `LifeContextService`
  - Builds `LifeContextBundle` objects by combining Obsidian notes, Garmin metrics, Google/Apple calendar events, correlation findings, variance analysis, and persistent memory snapshots.
  - `LifeContextFetcher` provides pluggable data providers; `LifeContextFormatter` converts bundles to Markdown/JSON depending on the consumer.
  - Used by `/export_context`, the AI assistant (`fetch_context` tool), and Smart Context Triggers.
- Export UX: `life_context_export_conversation.py`
  - Presets for metric selection (all, daily snapshot, notes focus, insights only) and custom metric entry.
  - Supports quick period shortcuts or arbitrary date ranges (validated, capped at 120 days) and Markdown/JSON output.
  - Streams the generated file plus a concise Telegram summary.
- `telegram_bot/service/correlation_engine`
  - `CorrelationEngine` processes aligned event timelines, applies statistical tests, and ranks significant relationships.
  - Variance analysis (`variance.py`) surfaces abnormal changes (e.g. sleep score dips) with configurable alert thresholds.
  - Event sources encapsulate Garmin and calendar fetchers; `CorrelationJobRunner` deduplicates events, assembles telemetry, and executes the engine.
- Assistant integration: correlation and variance metrics are exposed via `fetch_context` responses and feed into morning reports and smart triggers.

---

## Scheduled Tasks

- Scheduling: `ScheduledTaskService` (cron expressions via `aiocron`) plus `ScheduledJobsFacade` for interactive control.
- Morning Report (`scheduled_tasks/morning_report_task.py`)
  - Generates the daily “Poranny Brief Strategiczny” at the configured hour.
  - Pulls Garmin metrics (via `InfluxDBGarminDataExporter`), recent calendar events, Obsidian notes, and correlation summaries.
  - Runs summarisation through `LLMService` and delivers chunked messages to Telegram; failures are surfaced via callback notifications.
- Correlation Engine (`scheduled_tasks/correlation_engine_task.py`)
  - Nightly (configurable cron) job that orchestrates `CorrelationJobRunner` over calendar and Garmin events.
  - Sends a digest summarising significant correlations and variance alerts; gracefully reports failure via Telegram.
- Weekly Memory Consolidation (`scheduled_tasks/memory_consolidation_task.py`)
  - Batches the past week’s daily notes and AI logs, produces a reflective summary, and extracts persistent facts as deltas.
  - Invokes `PersistentMemoryUpdater` to apply add/update/remove operations with deterministic routing; notifies the user when finished.
- Obsidian Embedding Refresh (`scheduled_tasks/obsidian_embedding_task.py`)
  - Optional nightly job that calls `ObsidianEmbeddingIndexer.refresh_incremental()` to keep the semantic index in sync with the vault.
  - Logs processed/skipped/deleted counts; failures remain in logs and the job table for manual reruns.
- Smart Context Triggers (`scheduled_tasks/smart_context_trigger_task.py`)
  - Wraps `ContextTriggerExecutor` instances defined in config (e.g. smart nudges based on health data).
  - Each trigger executes independently, with structured logging and error capture to avoid crashing the scheduler.

### Persistent Memory Architecture

The memory consolidation system maintains a structured, long-term knowledge base (`persistent_memory.md`) with the following design:

**Document Structure:**
- YAML frontmatter with `consolidation_type`, `last_updated`, `tags`
- Fixed domain sections: "Zdrowie i Samopoczucie", "Praca i Produktywność", "Relacje i Kontakty", "Hobby i Zainteresowania", "Projekty Osobiste", "Finanse", "Systemy i Narzędzia", "Podróże"
- Each section contains a Markdown table with columns: `id`, `statement`, `category`, `confidence`, `first_seen`, `last_seen`, `sources`, `status`, `notes`

**Fact Lifecycle:**
- **Additions**: New facts get auto-generated IDs (category-based prefix + SHA1 hash)
- **Updates**: Existing facts are matched by ID or statement+category; timestamps and sources are merged
- **Removals**: LLM can mark facts as obsolete for deletion

**Services:**
- `PersistentMemoryUpdater`: Orchestrates read → diff → write workflow with section routing
- `PersistentMemoryDocument`: Parses/renders full document with frontmatter preservation
- `PersistentFact`: Immutable value object with merge capabilities

**Integration:**
- Weekly consolidation (Monday 2 AM) extracts facts from daily notes and AI logs
- LLM produces structured `PersistentMemoryLLMResponse` with per-section deltas
- Facts are routed to sections based on configurable category mappings
- Update summaries (add/update/remove counts) are logged and reported via Telegram
- Smart Context Triggers: `scheduled_tasks/smart_context_trigger_task.py`
  - `main.register_smart_context_triggers(...)` wires cron expressions from config to individual trigger tasks.
  - Each task wraps a `ContextTriggerExecutor` that gathers context, runs the analyzer, and decides whether to notify.
  - Successful triggers send priority-marked Telegram updates and log the result to the Obsidian AI log; failures are surfaced via Loguru and a fallback Telegram alert.

---

## Data & Persistence

- SQLite DB: `out/bot.db` via `DBService`:
  - `food_log(name, protein, carbs, fats, comment, datetime)`
  - `drug_log(name, dosage, datetime)`
  - `message_log(user_id, message_type, content, response, datetime)`
- Logs: `out/log/debug.log` (DEBUG) and `out/log/error.log` (ERROR).
- AI agent traces: `out/log/ai_assistant_traces.log`.
- Obsidian vault: configured in `ObsidianConfig` paths.

---

## Startup/Shutdown Behavior

- On startup: registers bot commands and sends a “Bot is up and functional” DM to `my_telegram_user_id`.
- On graceful shutdown: sends a “Bot is shutting down” DM and stops scheduler/workers (via `atexit`).

---

## Notable Implementation Details

- Telegram message chunking with Markdown fallback (`utils.send_message_chunks`).
- Safe Markdown cleaning/formatting for AI responses.
- Cron jobs enqueue heavy work into `BackgroundTaskExecutor` to keep the main loop responsive.
- Agents are provider-agnostic via `ModelFactory`/`ModelProvider` (OpenAI, Gemini, Anthropic, Ollama), configured by env.
- Life context exports reuse a single `LifeContextService` instance, ensuring consistent formatting between `/export_context`, smart triggers, and assistant tools.
- Persistent memory updates are delta-based: `PersistentMemoryUpdater.last_summary` captures add/update/remove counts for telemetry and operator feedback.
- `ScheduledJobsFacade` keeps an in-memory registry of cron jobs so `/scheduled_jobs` can display metadata and execute tasks on demand.

---

## Quick Map to Key Files

- Entrypoint & wiring: `telegram_bot/main.py`, `telegram_bot/service_factory.py`.
- AI assistant: `service/ai_assitant_service.py`, `ai_assistant/agents/*`, `ai_assistant/tools/applescript_tool.py`.
- Obsidian: `service/obsidian/obsidian_service.py`, `service/obsidian/obsidian_daily_notes_manager.py`.
- Voice: `service/message_transcription_service.py`, handlers in `handlers/messages/*`.
- Garmin: `service/garmin_connect_service.py`, `service/morning_report_service.py`, `handlers/commands/garmin_commands.py`, `handlers/conversations/garmin_*`.
- Scheduling & background: `service/scheduled_task_service.py`, `service/background_task_executor.py`.
- Ops commands: `handlers/commands/*`.


- Persistent memory micro‑extraction (daily)
  - Run a small nightly job to extract micro‑facts into `persistent_memory.md` instead of weekly only.
  - Where: reuse `memory_consolidation_task` logic with a daily cron and smaller window.
- Saved AppleScript macros
  - `/macro <name> [args]` that loads a script snippet from a configured directory and executes via the existing AppleScript tool.
  - Where: minimal storage + an execution wrapper; reuse `execute_applescript`.

- Semantic index CLI tooling (see `docs/plans/chromadb_integration_plan.md`)
  - Provide manual `refresh`, `rebuild`, and `query` commands plus progress logging for the embedding index.
  - Where: lightweight scripts under `tests/scripts/` that reuse `ServiceFactory` and `ObsidianEmbeddingIndexer`.

---

## Configuration Notes

- `BotSettings` aggregates environment-configured sections: Telegram token, user ID, Whisper, AI assistant config, Obsidian config, and scheduled tasks.
- Default LLM presets live in `telegram_bot/constants.py`.
- Ensure macOS host permissions for AppleScript automation (System Settings → Privacy & Security → Automation).

---

## Observed Strengths & Caveats

- Strengths: clear separation of concerns, robust iCloud/Obsidian I/O, async + background processing, good tooling hooks (AppleScript, MCP), and chunked Telegram output.
- Caveats: some commands are power-user oriented (invoking through AI); adding thin command wrappers for common automations will improve reliability and speed.
