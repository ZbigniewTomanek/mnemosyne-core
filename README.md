# Mnemosyne 🧠

## Personal AI Assistant with Long-term Memory & Proactive Health Analytics

![Mac Mini M4 Server](docs/server.png)

A self-hosted Telegram bot that serves as a personal intelligence system, combining Garmin health data, Obsidian notes, calendar events, and persistent memory into a unified "life context" with proactive insights and automation.

This project was presented at **[AI Tinkerers](https://aitinkerers.org/)** meetup as a technical deep dive into building a personal AI system.

---

## ⚠️ CRITICAL DISCLAIMERS

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ⚠️  READ BEFORE PROCEEDING                                           ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                      ┃
┃ • NOT MAINTAINED: This is a snapshot from my AI Tinkerers talk       ┃
┃   The codebase is tightly coupled to my personal infrastructure      ┃
┃   and Obsidian vault structure. Fork for learning, not deployment.   ┃
┃                                                                      ┃
┃ • NO GIT HISTORY: Fresh fork to remove private information           ┃
┃   (vault contents, personal details, API keys in commit history)     ┃
┃                                                                      ┃
┃ • SECURITY WARNING: NO PROMPT INJECTION DEFENSE!                     ┃
┃   The AI has significant system access and can:                      ┃
┃   - Execute arbitrary AppleScript (control macOS apps)               ┃
┃   - Write to your Obsidian vault                                     ┃
┃   - Access and modify calendar/reminders                             ┃
┃   - Send messages via iMessage, Mail, etc.                           ┃
┃                                                                      ┃
┃   A malicious event title could instruct the bot to:                 ┃
┃   - Exfiltrate data via iMessage/email                               ┃
┃   - Delete vault contents                                            ┃
┃   - Execute system commands                                          ┃
┃                                                                      ┃
┃   ONLY deploy in trusted, isolated environments with trusted inputs! ┃
┃                                                                      ┃
┃ • INFRASTRUCTURE DEPENDENCIES:                                       ┃
┃   - macOS (for AppleScript + launchctl)                              ┃
┃   - garmin-grafana running on same machine                           ┃
┃   - Obsidian vault with git sync                                     ┃
┃   - Apple ecosystem (Calendar, Messages, etc.)                       ┃
┃                                                                      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## What This Is

This project started as a simple Telegram interface for quickly adding notes to my Obsidian vault. Over time, it evolved into a comprehensive personal intelligence system that:

- **Aggregates multi-source data**: Garmin health metrics, Obsidian daily notes, Apple Calendar events, and LLM-maintained persistent memory
- **Provides proactive insights**: Scheduled analytics tasks (morning briefings, correlation detection, memory consolidation)
- **Enables voice-driven automation**: The killer feature—voice commands that actually work (like Siri should be)

### Quick Example Use Cases

**Voice-Driven Automation:**
```
🎤 "Remind me to pay taxes next week and message Jane about dinner"
   → Creates Apple Reminder + sends iMessage automatically
```

**Health & Activity Analysis:**
```
📊 "How did my yoga retreat compare to my climbing trip for recovery?"
   → Analyzes Garmin HRV, sleep quality, stress levels across date ranges
   → Includes correlation data and variance analysis
   → Cross-references with Obsidian notes from those periods
```

**Semantic Search:**
```
🔍 "Find notes about coffee brewing experiments"
   → Multilingual semantic search across entire Obsidian vault
   → ChromaDB-backed with paraphrase-multilingual embeddings
```

**Proactive Notifications:**
```
🔔 Smart context trigger: "Your HRV has been declining for 3 days
   and sleep quality is 15% below baseline. Consider rest day."
```

### Why This Exists

I struggled with focus and needed systems to help me remember things and track patterns. As someone who loves collecting and analyzing data, I iteratively built this AI assistant to be maximally helpful for my specific needs. This is not a commercial project—it's a hobby system built for personal use.

---

## Architecture Overview

### Data Sources Flow

```
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   Garmin        │  │   Obsidian       │  │  Apple Calendar  │
│   Health Data   │  │   Daily Notes    │  │  & Reminders     │
│                 │  │                  │  │                  │
│ • Sleep         │  │ • Reflections    │  │ • Events         │
│ • HRV           │  │ • Activities     │  │ • Meetings       │
│ • Heart Rate    │  │ • Health logs    │  │ • Tasks          │
│ • Stress        │  │ • Gratitude      │  │                  │
│ • Body Battery  │  │ • Work notes     │  │                  │
└────────┬────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                    │                       │
         └────────────────────┴───────────────────────┘
                              ↓
                    ┌─────────────────────┐
                    │ Correlation Engine  │
                    │ • Statistical tests │
                    │ • Variance analysis │
                    └──────────┬──────────┘
                              ↓
         ┌────────────────────┴────────────────────┐
         │         Life Context Service            │
         │  (Unified data aggregation & formatting)│
         └──────────┬──────────────────────────────┘
                    │
         ┌──────────┴──────────┐
         │                     │
         ↓                     ↓
┌─────────────────┐   ┌──────────────────────┐
│  AI Assistant   │   │  Persistent Memory   │
│  (Telegram)     │←──│  (LLM-maintained)    │
│                 │   │                      │
│ • Tools         │   │ • Health facts       │
│ • Handoffs      │   │ • Relationships      │
│ • Context       │   │ • Preferences        │
└─────────────────┘   │ • Projects           │
                      └──────────────────────┘
```

### Core Components

**AI Agent System** (`ai_assistant/`)
- Built on OpenAI Agents framework
- Atomic tools for Obsidian, AppleScript, semantic search, web search
- Handoffs to specialized agents (Obsidian MCP agent, product search)
- Local filesystem tracing for debugging

**Scheduled Analytics** (`telegram_bot/scheduled_tasks/`)
- Morning briefings (Garmin summary + calendar + notes)
- Nightly correlation engine (statistical analysis of events × health metrics)
- Weekly memory consolidation (extract facts from week's notes)
- Obsidian embedding refresh (incremental ChromaDB updates)
- Smart context triggers (proactive health notifications)

**Life Context Service** (`telegram_bot/service/life_context/`)
- Single source of truth for data aggregation
- Reusable across commands, scheduled tasks, and AI tools
- Configurable metric selection and date ranges
- Exports to Markdown or JSON

**Obsidian Integration** (`telegram_bot/service/obsidian/`)
- Safe concurrent file I/O (async locks + fcntl)
- iCloud placeholder waiting
- Git sync integration
- LLM-assisted note tagging and AI reflection logging

**Garmin Data Pipeline** (`telegram_bot/service/influxdb_garmin_data_exporter.py`)
- Exports from garmin-grafana InfluxDB via docker exec + cp
- Retry logic with exponential backoff for transient errors
- Returns structured pandas DataFrames with 14 metric types

**Voice Transcription** (`telegram_bot/service/message_transcription_service.py`)
- faster-whisper in process pool
- Configurable model size
- Transcripts wrapped in context prompt to mitigate ASR errors

**Semantic Search** (`telegram_bot/service/obsidian/obsidian_embedding_indexer.py`)
- ChromaDB vector store
- Recursive chunking strategy
- Metadata tracking (path, checksum, mtime)
- Multilingual embeddings (Polish + English)

---

## Technical Deep Dive

### 🎯 Key Insights from Building This

These are the hard-won lessons from building a personal AI system over months of iteration.

#### 1. Context Management is Everything

**The Problem:**
Raw data dumps to LLMs lead to poor responses, hallucinations, and wasted tokens.

**The Solution:**
Pre-process, aggregate, and structure data before presenting to the AI.

```python
# ❌ DON'T: Dump raw data and ask LLM to compute
prompt = f"Analyze my last 30 days of Garmin data: {json.dumps(raw_garmin_data)}"
# Result: overwhelming context, hallucinations, inconsistent analysis

# ✅ DO: Pre-process and provide structured context
life_context = LifeContextService.fetch(
    date_range="2025-10-01 to 2025-10-30",
    include=[
        "daily_stats",        # Pre-computed Garmin aggregates
        "correlations",       # Statistical correlation analysis
        "variance_alerts",    # Abnormal pattern detection
        "notes"              # Relevant Obsidian excerpts
    ]
)
# Result: Clean markdown/JSON, accurate insights, consistent formatting
```

**Impact:**
- Dramatically reduced hallucinations (LLM sees pre-computed facts, not raw numbers)
- Improved response quality (consistent aggregation logic)
- Faster responses (smaller context window)
- Reusable across commands, scheduled tasks, and agent tools

**Implementation Details:**
- Single `LifeContextService` instance with pluggable data providers
- `LifeContextFormatter` handles Markdown/JSON serialization
- Used by: `/export_context` command, `fetch_context` tool, smart context triggers
- See: `telegram_bot/service/life_context/`

---

#### 2. Agent Design Patterns: Atomic Tools

**The Problem:**
Current agent frameworks (as of late 2024) struggle with complex, multi-step tools. They burn tokens and produce unstable results.

**The Solution:**
Expose atomic, single-purpose operations. Let the agent orchestrate the workflow.

```python
# ✅ WORKS: Atomic, single-purpose tool
def log_daily_note(note_content: str) -> str:
    """Append timestamped note to today's daily note with LLM tagging.

    Single responsibility: write note + generate tags.
    """
    # 1. Ensure daily note exists
    # 2. LLM generates 2-5 tags from content
    # 3. Append timestamped note
    # 4. Return confirmation
    return "Note logged successfully"

# ❌ UNSTABLE: Complex, multi-step tool
def analyze_and_create_weekly_plan(goals: list[str]) -> str:
    """Fetch context, analyze trends, generate insights, create notes,
    update memory, send notifications, schedule follow-ups..."""
    # Too much in one tool!
    # Result: Token explosion, unpredictable behavior, hard to debug
```

**The Trade-off:**
- More tool calls (agent orchestrates multi-step workflows)
- vs. Stability and predictability

**I chose stability.**

**Explicit Flow Instructions:**
Even with atomic tools, current models need explicit guidance:

```python
AGENT_INSTRUCTIONS = """
When user shares a reflection or information:
1. First, log the note to Obsidian using log_daily_note
2. Then, if the information seems important for long-term memory,
   mention it will be picked up in weekly consolidation
3. Confirm what you did

Do NOT try to update persistent memory directly—that happens weekly.
"""
```

**Impact:**
- Predictable agent behavior
- Easier debugging (inspect individual tool calls)
- Lower token costs per interaction
- Clear separation of concerns

**See:**
- `ai_assistant/agents/ai_assistant_agent.py` - Agent definition with atomic tools
- `ai_assistant/tools/` - Individual tool implementations

---

#### 3. Multilingual Embedding Challenges

**The Problem:**
My Obsidian vault is in Polish. Standard English-optimized embedding models failed.

```python
# ❌ FAILED: English-optimized model
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
# Result on Polish queries: Terrible recall, irrelevant results

# ✅ SOLUTION: Multilingual model
embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
# Result: Semantic search finally works!
```

**Lesson:**
Don't assume English-optimized models generalize to other languages, even "similar" European languages.

**Additional Constraint:**
Small models that fit in 16GB RAM (<7B parameters for LLMs, smaller for embeddings) struggle with non-English text. The multilingual embedding model is larger but essential.

**Impact:**
- Semantic search became actually useful
- Can find notes based on conceptual similarity, not just keywords
- Works across Polish and English notes

**See:**
- `telegram_bot/service/obsidian/obsidian_embedding_indexer.py`

---

#### 4. Persistent Memory Architecture

**The Challenge:**
How do you maintain long-term memory for an AI assistant without:
- Exponentially growing context windows
- Losing important information
- Manual curation overhead
- Losing human-readability (I want to read/edit my vault)

**The Solution:**
Structured markdown tables with delta-based updates.

**Document Structure:**
```markdown
---
consolidation_type: persistent
last_updated: 2025-10-15
tags: [ai_memory, persistent_facts]
---

## Health and Well-being

| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |
|---|---|---|---|---|---|---|---|---|
| health-hrv-recovery | HRV >70ms correlates with better recovery | bio-signal | high | 2025-09 | 2025-10 | garmin,notes | active | Consistent pattern across 12 weeks |
| health-sleep-routine | Sleep quality improves with 10 PM bedtime | sleep | high | 2025-08 | 2025-10 | garmin,notes | active | 23% better sleep score vs 11 PM |

## Work and Productivity

| id | statement | category | confidence | first_seen | last_seen | sources | status | notes |
|---|---|---|---|---|---|---|---|---|
| work-peak-hours | Most productive in first 2-3 hours of the day | productivity | high | 2025-05 | 2025-10 | notes | active | |
```

**Design Decisions:**

1. **Markdown tables, not JSON**
   - Human-readable in Obsidian
   - Can be edited manually if needed
   - Still parseable programmatically

2. **Deterministic IDs**
   - Format: `{category-prefix}-{sha1_hash(statement)[:12]}`
   - Example: `health-hrv-recovery`
   - Allows matching across updates

3. **Delta-based updates**
   - LLM produces add/update/remove operations
   - Not a full rewrite each time
   - Preserves `first_seen`, merges `sources`

4. **Domain-based routing**
   - 8 fixed sections: Health, Work, Relationships, Hobbies, Projects, Finance, Systems, Travel
   - Facts routed by category mapping
   - Maintains organization

5. **Weekly consolidation process**
   - Extracts facts from past week's daily notes + AI logs
   - LLM generates structured `PersistentMemoryLLMResponse`
   - `PersistentMemoryUpdater` applies deltas
   - Reports add/update/remove counts via Telegram

**Why This Works:**
- Bounded context (table rows, not exponential growth)
- Semantic compression (facts, not raw notes)
- Human-in-the-loop (I can review/edit the memory file)
- Deterministic updates (no drift from repeated rewrites)

**See:**
- `telegram_bot/service/memory/persistent_memory_updater.py` - Update orchestration
- `telegram_bot/service/memory/persistent_memory_document.py` - Parsing and rendering
- `telegram_bot/service/memory/persistent_fact.py` - Fact data model
- `telegram_bot/scheduled_tasks/memory_consolidation_task.py` - Weekly consolidation
- `docs/example-obsidian-vault/30 AI Assistant/memory/persistent_memory.md` - Example

---

#### 5. Garmin Data Integration Trade-offs

**Current Implementation:**
```python
# Export data from garmin-grafana container
async def export_data(days: int = 7) -> GarminExportData:
    # 1. Run influxdb_exporter.py in container (with retry logic)
    result = await docker_exec([
        "docker", "exec", "garmin-fetch-data",
        "uv", "run", "/app/garmin_grafana/influxdb_exporter.py",
        f"--last-n-days={days}"
    ])

    # 2. Docker cp ZIP file to temp directory
    await docker_cp(f"{container}:/tmp/{zip_filename}", temp_path)

    # 3. Extract CSVs → pandas DataFrames
    return parse_csvs(extract_dir)
```

**Trade-offs:**
- ❌ Laggy (~1-2 minute overhead for docker operations)
- ✅ Leverages existing garmin-grafana infrastructure
- ✅ No need to maintain separate InfluxDB client
- ✅ Retry logic handles transient network errors

**Retry Logic:**
```python
# Exponential backoff for transient errors
transient_errors = [
    "name or service not known",
    "failed to resolve",
    "max retries exceeded",
    "connection refused",
    "network is unreachable"
]

for attempt in range(1, max_retries + 1):
    result = await run_command(cmd)
    if result.returncode == 0:
        return result
    if is_transient_error(result.stderr):
        await asyncio.sleep(delay)
        delay *= backoff_factor
        continue
    break
```

**Lesson:**
Pragmatism > perfection. Leveraging existing tools (even if slightly inefficient) beats building from scratch when you're a solo developer.

**See:**
- `telegram_bot/service/influxdb_garmin_data_exporter.py` - Full implementation with retry logic and detailed docstrings

---

### 🛠️ Agent Stack Details

**Primary Agent:** `AIAssistant` (OpenAI Agents framework)

**Tools:**
- **`log_daily_note(note_content: str)`**
  - Appends timestamped note to today's Obsidian daily note
  - LLM generates 2-5 tags automatically
  - Creates note if it doesn't exist
  - Triggers AI reflection logging

- **`fetch_context(date_range: str, include: list[str])`**
  - Assembles life context bundles
  - Configurable metrics: Garmin stats, notes, calendar, correlations, variance, memory
  - Returns structured Markdown or JSON
  - Used for health queries, period comparisons, insights

- **`execute_applescript(script: str)`**
  - Executes AppleScript via `/usr/bin/osascript`
  - Control macOS apps: Notes, Calendar, Mail, Finder, Safari, Reminders, Messages
  - No confirmation prompts (trusted user environment)
  - Security risk if inputs are untrusted!

- **`semantic_search(query: str, limit: int)`**
  - ChromaDB-backed search across Obsidian vault
  - Multilingual embeddings (Polish + English)
  - Returns scored snippets with vault links
  - Metadata: relative_path, checksum, mtime

- **`WebSearchTool`**
  - Fresh information from public web
  - Used only when local context is insufficient
  - Bias toward local data first

**Handoffs (specialized sub-agents):**
- **`ObsidianAgent`** (MCP filesystem server)
  - Advanced vault operations beyond simple semantic search
  - Primitives: read, write, edit, list, search, get_file_info
  - Runs in Docker with vault mounted
  - Delegated for complex vault queries/edits

- **`PolishProductSearchAgent`**
  - Structured workflow for Polish e-commerce research
  - Multi-step: search → filter → compare → format
  - Returns Pydantic models (not plain text)

**Agent Instructions Bias:**
- Default to Obsidian note capture for reflections/information
- Delegate vault questions to Obsidian agent or semantic tool
- Fetch life context before answering health/schedule questions
- Use AppleScript for messaging/automation without redundant confirmation
- Web/product search only when local context insufficient

**Tracing:**
- `LocalFilesystemTracingProcessor` writes agent traces to `out/log/ai_assistant_traces.log`
- Essential for debugging tool calls, handoffs, and decision-making
- See: `ai_assistant/tracing/local_filesystem_tracing_processor.py`

---

### ⏰ Scheduled Tasks Architecture

All tasks managed by `ScheduledTaskService` (cron expressions via `aiocron`) with manual trigger support via `/scheduled_jobs` command.

#### 1. Morning Report (daily, configurable hour)

**Purpose:** Daily strategic briefing delivered to Telegram

**Data Sources:**
- Garmin metrics (via InfluxDB export)
  - Contiguous day summaries
  - Sleep quality, HRV, stress, Body Battery
  - Recent activities
- Recent calendar events
- Obsidian notes snippets
- Correlation summaries

**Process:**
1. Gather last 7 days of Garmin data
2. Extract calendar events (past 24h + next 24h)
3. Pull relevant Obsidian notes
4. LLM summarization (configurable model)
5. Chunked delivery via Telegram (respects message limits)

**Error Handling:**
- Failures surfaced via callback notification
- Logged to `out/log/debug.log`

**See:** `telegram_bot/scheduled_tasks/morning_report_task.py`

---

#### 2. Correlation Engine (nightly, configurable cron)

**Purpose:** Statistical analysis of relationships between life events and health metrics

**Process:**
1. `CorrelationJobRunner` fetches events from:
   - Garmin (activities, sleep, stress patterns)
   - Calendar (meetings, travel, social events)
2. Deduplicates and aligns event timelines
3. `CorrelationEngine` applies statistical tests:
   - Pearson correlation
   - Spearman rank correlation
   - Time-lagged correlations (events → health outcomes)
4. Variance analysis detects abnormal changes:
   - Sleep score dips
   - HRV deviations
   - Stress spikes
5. Generates digest with significant findings
6. Delivers via Telegram

**Example Findings:**
- "High-intensity meetings (>3/day) correlate with 18% lower HRV next day (p<0.05)"
- "Sleep quality drops 23% when bedtime >11 PM (variance alert)"

**Configuration:**
- Alert thresholds (e.g., p-value < 0.05)
- Minimum effect size
- Lookback window (default: 90 days)

**See:**
- `telegram_bot/service/correlation_engine/` - Full engine implementation
- `telegram_bot/scheduled_tasks/correlation_engine_task.py` - Scheduled runner

---

#### 3. Weekly Memory Consolidation (Monday 2 AM)

**Purpose:** Extract persistent facts from the week's notes and update long-term memory

**Process:**
1. Batch past week's:
   - Daily notes (reflections, activities, health logs)
   - AI logs (assistant reflections)
2. LLM extracts structured facts:
   ```python
   class PersistentMemoryLLMResponse(BaseModel):
       health: list[MemoryDelta]          # Add/update/remove facts
       work: list[MemoryDelta]
       relationships: list[MemoryDelta]
       # ... 8 sections total
   ```
3. `PersistentMemoryUpdater` applies deltas:
   - **Add**: New facts with generated IDs
   - **Update**: Match by ID or statement+category, merge sources/timestamps
   - **Remove**: Mark as deleted/obsolete
4. Write updated `persistent_memory.md` to Obsidian vault (as git commit)
5. Report summary to user:
   - "Added 7 facts, updated 3, removed 1"

**Deterministic ID Generation:**
```python
def generate_id(statement: str, category: str) -> str:
    prefix = CATEGORY_PREFIXES[category]  # e.g., "health"
    hash_suffix = hashlib.sha1(statement.encode()).hexdigest()[:12]
    return f"{prefix}-{hash_suffix}"
```

**See:**
- `telegram_bot/scheduled_tasks/memory_consolidation_task.py`
- `telegram_bot/service/memory/` - Full memory update logic

---

#### 4. Obsidian Embedding Refresh (nightly, optional)

**Purpose:** Keep semantic search index in sync with vault

**Process:**
1. `ObsidianEmbeddingIndexer.refresh_incremental()`
2. Walk vault directory tree
3. For each `.md` file:
   - Check checksum against ChromaDB metadata
   - If changed: re-chunk and re-embed
   - If deleted: remove from index
   - If new: add to index
4. Log counts:
   - Processed: X files
   - Skipped (unchanged): Y files
   - Deleted: Z files

**Performance:**
- Incremental (only processes changes)
- Typical run: <30s for 500-file vault with ~10 daily changes

**See:** `telegram_bot/service/obsidian/obsidian_embedding_indexer.py`

---

#### 5. Smart Context Triggers (configurable cron)

**Purpose:** Proactive notifications based on health data patterns

**Architecture:**
- `ContextTriggerExecutor` instances defined in config
- Each trigger:
  1. Gathers relevant context (via `LifeContextService`)
  2. Runs analyzer (LLM or rule-based)
  3. Decides whether to notify
  4. Sends priority-marked Telegram message
  5. Logs result to Obsidian AI log

**Example Trigger:**
```python
class HRVDeclineTrigger(ContextTriggerExecutor):
    """Notify if HRV declining for 3+ days."""

    async def execute(self):
        context = await self.life_context.fetch(
            date_range="last 7 days",
            include=["daily_stats", "hrv_intraday"]
        )

        # Analyze trend
        hrv_trend = analyze_hrv_decline(context.hrv_data)

        if hrv_trend.declining_days >= 3:
            await self.notify(
                f"⚠️ HRV declining for {hrv_trend.declining_days} days. "
                f"Current: {hrv_trend.current_avg}ms (baseline: {hrv_trend.baseline}ms). "
                f"Consider rest day."
            )
```

**Configuration:**
```python
# In BotSettings
smart_context_triggers = [
    {
        "name": "hrv_decline",
        "executor_class": "HRVDeclineTrigger",
        "cron": "0 9 * * *",  # Daily at 9 AM
        "enabled": True
    }
]
```

**Error Handling:**
- Triggers run independently (one failure doesn't crash others)
- Failures logged and reported via Telegram alert

**See:**
- `telegram_bot/scheduled_tasks/smart_context_trigger_task.py`
- `telegram_bot/service/context_triggers/` - Trigger implementations

---

## How This Was Built: AI-Assisted Development Flow

### Codebase Stability Through Structured Development

Despite being a personal hobby project vibe-coded over months, this codebase remains pretty structured and stable. This is my flow that achieved that, I developed it iteratively and I guess it will change soon.

### The Development Flow

Most of this project was "vibe-coded" using **$20/month plans of Claude Code and Codex**. Here's the 7-step process:

#### 1. **Intent Clarification** (Chat-based LLM)
- Start with rough idea or feature request
- Chat with LLM to clarify intentions, explore edge cases, ask "what if" questions
- Refine requirements until crystal clear
- Example: "I want correlation detection" → "I need statistical correlation analysis between calendar events and Garmin metrics with configurable p-value thresholds and time-lagged analysis"
- Here I use CLI Tool to Copy relevant context into something like google gemini

#### 2. **Context Gathering & Planning** (Codex)
- Codex gathers current codebase context (existing architecture, related files, patterns)
- Creates detailed implementation plan
- Saves plan to `docs/plans/{feature_name}_plan.md`
- Example plans in repo:
  - `docs/plans/life_context_plan.md`
  - `docs/plans/memory_refactor_plan.md`
  - `docs/plans/chromadb_integration_plan.md`

**Why this matters:**
- Plans serve as reusable context for future LLM sessions
- Documents architectural decisions
- Prevents scope creep (LLM stays focused on plan)

#### 3. **Plan Review & Correction**
- Human review of generated plan
- Catch architectural issues early (before any code is written)
- Refine approach, identify missing edge cases
- Update plan markdown file

**The meta-trick:**
Having LLMs review their own plans with fresh context often catches issues. I sometimes feed the plan back to a different model and ask: "What's wrong with this approach?"

#### 4. **TDD Implementation** (Codex)
- Codex implements features in Test-Driven Development style
- Write tests first, then implementation
- Iterate until tests pass
- Follow existing patterns from codebase
- It's important to tell it to follow SOLID principles so the design is modular and replaceble

**Benefits:**
- Tests serve as executable specifications
- Regression safety for future refactors
- Forces thinking about interfaces before implementation

#### 5. **Code Review** (Claude Code)
- Claude Code reviews the implementation
- Checks for: logic errors, edge cases, performance issues, maintainability
- Suggests improvements
- Ensures consistency with existing codebase patterns

**Why separate review step:**
The LLM that wrote the code has cognitive biases toward its own solution. Fresh LLM review catches issues the original missed.

#### 6. **Manual Testing Scripts** (`tests/scripts/`)
- Write manual test scripts for exploratory testing
- Test scripts live in `tests/scripts/` (not committed, gitignored)
- Used for:
  - Testing with real data (Obsidian vault, Garmin API)
  - Debugging edge cases
  - Validating end-to-end workflows

**Example scripts:**
```python
# tests/scripts/test_correlation_engine.py
# Manual script to run correlation engine on last 90 days and print results

# tests/scripts/rebuild_embeddings.py
# Manual script to rebuild ChromaDB index from scratch

# tests/scripts/test_memory_consolidation.py
# Manual script to test memory consolidation on specific date range
```

#### 7. **Documentation Updates**
Two critical documentation files kept in sync:

**`docs/bot_functionality_overview.md`**
- **Purpose**: Single source of truth for bot functionality and architecture
- **Audience**: LLMs (and humans who want comprehensive overview)
- **Updated**: After every significant feature addition
- **Why**: Enables future LLM sessions to understand the system without re-reading entire codebase
- **Size**: Comprehensive (~290 lines covering all major components)

**`CLAUDE.md`** (project instructions)
- **Purpose**: Development guidelines, coding standards, LLM instructions
- **Content**:
  - "Always read entire files" (no partial edits without full context)
  - "Commit early and often"
  - "Look up latest library syntax" (LLM knowledge may be outdated)
  - "No dummy implementations"
  - "Ask clarifying questions"
  - Package management commands (`uv` usage)
  - Testing commands
  - Linting and type-checking
- **Why**: Ensures consistent LLM behavior across sessions
- **Updated**: When new patterns emerge or lessons are learned

### Files That Make This Work

```
mnemosyne-core/
├── CLAUDE.md                           # LLM development instructions
├── docs/
│   ├── bot_functionality_overview.md  # Comprehensive system overview (for LLMs)
│   └── plans/                          # Feature implementation plans
│       ├── life_context_plan.md
│       ├── memory_refactor_plan.md
│       ├── chromadb_integration_plan.md
│       └── bio_signal_correlation_engine/
│           ├── bio_signal_correlation_engine_plan.md
│           ├── bio_signal_correlation_engine_stage1.md
│           ├── bio_signal_correlation_engine_stage2_plan.md
│           └── bio_signal_correlation_engine_stage3_plan.md
└── tests/
    └── scripts/                        # Manual testing scripts (gitignored)
        ├── test_correlation_engine.py
        ├── rebuild_embeddings.py
        └── test_memory_consolidation.py
```

---

## Example Obsidian Vault Structure

The bot expects a specific Obsidian vault structure. See `docs/example-obsidian-vault/` for a sanitized example.

### Daily Notes

```
01 management/10 process/0 daily/2025-10-15.md
```

**Structure:**
- YAML frontmatter (creation date, tags, day of week)
- Daily checklist sections (Morning/Evening well-being, Body Battery)
- Health tracking (sleep, dreams, supplements, medications, substances)
- Notes sections (gratitude, work, various thoughts)
- Meta-bind inputs for interactive data entry

**Example:**
```markdown
---
creation date: 2025-10-15 09:42
tags: DailyNote 2025
day: Tuesday
---

# 2025-10-15 Tuesday

<< [[2025-10-14]] | [[2025-10-16]]>>

## ✅ Daily Check List

>[!dream] What did you dream about?
>Had an interesting dream about attending a technical conference...

### Morning
Well-being: [meta-bind input]
Body Battery: [meta-bind input]

- [ ] Sun exposure
- [ ] Supplements

## 📖 Various thoughts

[Timestamped notes added by bot via log_daily_note tool]
```

### AI Memory System

```
30 AI Assistant/memory/
├── persistent_memory.md        # Long-term facts (8 domain tables)
├── logs/
│   └── 2025-10-15_ai_log.md   # Daily AI reflections
└── 2025-W42_memory.md          # Weekly consolidation summary
```

**Persistent Memory Structure:**
- 8 fixed sections: Health, Work, Relationships, Hobbies, Projects, Finance, Systems, Travel
- Each section contains a markdown table with fact columns
- See `docs/example-obsidian-vault/30 AI Assistant/memory/persistent_memory.md`

**Daily AI Logs:**
- Generated after each `log_daily_note` call
- LLM-generated reflection on the day's note
- Structured format for weekly consolidation

**Weekly Memory:**
- Summary of the week's events and insights
- Source for persistent memory extraction

### Git Synchronization

**Important:** All Obsidian vault modifications are performed as git commits:
- Daily note creation/updates
- AI log additions
- Persistent memory updates

The bot uses `ObsidianService` with:
- Intra-process async locks (per-path)
- Inter-process file locks (`fcntl`)
- Optional pre-write `git fetch/checkout` of target files

---

## Infrastructure Requirements

### Hardware

**Recommended:**
- **Mac Mini M4 16GB** (or equivalent Apple Silicon)
  - Self-hosted on macOS (required for AppleScript + launchctl)
  - 16GB RAM supports local models (faster-whisper, small LLMs)
  - Energy-efficient 24/7 operation

**See:** `docs/server.png` for my setup

### Software Dependencies

#### Required

1. **garmin-grafana** - [github.com/arpanghosh8453/garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana)
   - **Must run on same machine as bot**
   - Provides InfluxDB with Garmin health data
   - Bot exports via `docker exec` + `docker cp`

2. **Obsidian Vault**
   - **Git synchronization required** (all vault modifications are git commits)
   - iCloud sync optional but recommended for mobile access
   - Expected structure: see `docs/example-obsidian-vault/`

3. **Apple Ecosystem** (macOS required)
   - Calendar (event integration)
   - Messages (iMessage automation)
   - Notes (AppleScript automation)
   - Mail (email automation)
   - Reminders (task automation)
   - System Preferences: Privacy & Security → Automation permissions granted

4. **Telegram Bot**
   - Bot token from [@BotFather](https://t.me/BotFather)
   - Your Telegram user ID (for access control)

5. **Docker**
   - For garmin-grafana container
   - For Obsidian MCP agent

#### Optional

- **Garmin Device** (for Garmin integration)
  - Any Garmin device with health tracking
  - Garmin Connect account

- **Google Calendar API** (for extended calendar features)
  - OAuth2 credentials
  - See `telegram_bot/service/calendar/` for implementation

### Python Environment

- **Python 3.13** (specified in `pyproject.toml`)
- **uv** package manager (recommended)

```bash
# Install dependencies
uv sync

# Run bot
uv run python -m telegram_bot.main
```

### Environment Variables

Create `.env` file in project root:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
MY_TELEGRAM_USER_ID=your_user_id_here

# LLM Providers (configure at least one)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
```

You also need to configure properties in the `config.py`

---

## Bot Commands Reference

### Context & Search

| Command | Description |
|---------|-------------|
| `/export_context` | Interactive flow to export life context (notes, Garmin, correlations, variance, memory) for chosen date range and format (Markdown/JSON) |
| `/search_obsidian <query>` | Semantic search across Obsidian vault with Markdown-formatted results and vault links |
| `/scheduled_jobs` | Browse registered cron jobs, inspect metadata, and trigger a job immediately |

### Health & Daily Logs

| Command | Description |
|---------|-------------|
| `/log_food` | Multi-step conversation to log food item with macros and comments into SQLite |
| `/list_food [limit]` | List latest food entries (default 10) with macro breakdown |
| `/log_drug` | Guided conversation to record medication name and dosage multipliers |
| `/list_drugs [limit]` | Show recent medication entries |

### Garmin Integration

| Command | Description |
|---------|-------------|
| `/connect_garmin` | Email → password → optional MFA flow storing user tokens securely |
| `/garmin_status` | Report whether current user is connected |
| `/garmin_export` | Interactive export builder with format (Markdown, aggregated JSON, raw JSON) and date range selection |
| `/disconnect_garmin` | Revoke Garmin tokens by purging token directory |

### Operations & Environment Management

| Command | Description |
|---------|-------------|
| `/list_env` | List variable names detected in `.env` with line numbers |
| `/read_env KEY` | Print value for a variable (with safety guard for large payloads) |
| `/set_env KEY VALUE` | Insert or update entries in `.env`, including JSON string normalization |
| `/read_env_file KEY` | Send variable value as file when it exceeds chat limits |
| `/set_env_file KEY` | Start file-upload conversation that writes uploaded value into `.env` |
| `/get_logs [lines]` | Send tail of `out/log/debug.log` and request LLM summary |
| `/restart` | Reply with acknowledgement and invoke `BotRestartService.restart()` |

### Utility

| Command | Description |
|---------|-------------|
| `/cancel` | Available in every conversation to abort flow and clear state |

### Message Handlers

- **Text Messages**: Routed to `AIAssistantService.run_ai_assistant()` (free-form chat with context)
- **Voice Messages**: Downloaded, transcribed with faster-whisper, echoed, then forwarded to AI assistant with voice-specific prompt context

---

## Project Structure

```
mnemosyne-core/
├── ai_assistant/                    # AI agent system
│   ├── agents/
│   │   ├── ai_assistant_agent.py   # Primary agent with tools + handoffs
│   │   └── sub_agents/             # Specialized agents (Obsidian MCP, product search)
│   ├── tools/                      # Individual tool implementations
│   │   ├── applescript_tool.py
│   │   ├── obsidian_tool.py
│   │   ├── semantic_search_tool.py
│   │   └── web_search_tool.py
│   └── tracing/                    # Agent tracing infrastructure
│       └── local_filesystem_tracing_processor.py
│
├── telegram_bot/                    # Bot implementation
│   ├── main.py                     # Entry point, handler registration
│   ├── service_factory.py          # Dependency injection
│   │
│   ├── handlers/                   # Message/command handlers
│   │   ├── commands/               # Direct commands (/list_food, etc.)
│   │   ├── conversations/          # Multi-step flows (Garmin auth, context export)
│   │   └── messages/               # Text and voice message handlers
│   │
│   ├── service/                    # Core services
│   │   ├── ai_assitant_service.py
│   │   ├── db_service.py           # SQLite for food/medication logs
│   │   ├── message_transcription_service.py
│   │   ├── influxdb_garmin_data_exporter.py
│   │   │
│   │   ├── obsidian/               # Obsidian integration
│   │   │   ├── obsidian_service.py
│   │   │   ├── obsidian_daily_notes_manager.py
│   │   │   └── obsidian_embedding_indexer.py
│   │   │
│   │   ├── correlation_engine/     # Statistical analysis
│   │   │   ├── correlation_engine.py
│   │   │   ├── variance.py
│   │   │   └── correlation_job_runner.py
│   │   │
│   │   ├── life_context/           # Unified context service
│   │   │   ├── life_context_service.py
│   │   │   ├── life_context_fetcher.py
│   │   │   └── life_context_formatter.py
│   │   │
│   │   └── memory/                 # Persistent memory system
│   │       ├── persistent_memory_updater.py
│   │       ├── persistent_memory_document.py
│   │       └── persistent_fact.py
│   │
│   ├── scheduled_tasks/            # Cron jobs
│   │   ├── morning_report_task.py
│   │   ├── correlation_engine_task.py
│   │   ├── memory_consolidation_task.py
│   │   ├── obsidian_embedding_task.py
│   │   └── smart_context_trigger_task.py
│   │
│   └── constants.py                # Default LLM presets, config

├── tests/                          # Test suite
│   ├── service/                    # Service tests (Garmin, Obsidian, etc.)
│   └── data/                       # Mock data for testing

├── docs/                           # Documentation
│   ├── bot_functionality_overview.md
│   ├── example-obsidian-vault/     # Sanitized vault example
│   ├── plans/                      # Implementation plans
│   └── 3rdparty/                   # External API documentation

├── out/                            # Runtime output (gitignored)
│   ├── log/
│   │   ├── debug.log
│   │   ├── error.log
│   │   └── ai_assistant_traces.log
│   └── bot.db                      # SQLite database

├── setup-bot.sh                    # macOS LaunchAgent setup
├── run-bot.sh                      # Bot runner script
├── monitor-git-updates.sh          # Auto-update on git changes
└── pyproject.toml                  # Dependencies (uv)
```

---

## Known Limitations & Caveats

### Security

1. **No Prompt Injection Defense**
   - AI has significant system access (AppleScript, vault writes, calendar)
   - Malicious input could exfiltrate data or damage vault
   - **Trust boundary: Telegram user ID only** (single-user system)
   - Not suitable for multi-user deployment

2. **AppleScript Execution**
   - No sandboxing or validation
   - Can control any macOS app with automation permissions
   - Requires explicit system permissions (Privacy & Security settings)

### Performance

3. **Garmin Data Lag**
   - Exports via `docker exec` + `docker cp` (~1-2 minute overhead)
   - Not real-time (fine for daily analytics, not for live monitoring)
   - Trade-off for leveraging existing garmin-grafana infrastructure

4. **Voice Transcription Latency**
   - faster-whisper runs in process pool (CPU-bound)
   - ~5-15 seconds for typical voice message (depends on model size)

### Platform Constraints

5. **macOS-only**
   - AppleScript integration requires macOS
   - launchctl service (Linux equivalent: systemd)
   - Could be ported with significant refactoring (remove AppleScript, use alternative calendar/messaging APIs)

6. **Single-user Design**
   - Tightly coupled to my personal infrastructure
   - Hardcoded assumptions about vault structure
   - No multi-tenant support

### Language Support

7. **Polish Language Requirements**
   - Requires multilingual embedding models (larger, slower)
   - Small models (<16GB RAM) struggle with non-English text
   - English-optimized models fail on Polish semantic search

### Maintenance

8. **No Backward Compatibility**
   - Personal project, refactored aggressively when needed
   - Breaking changes without migration paths
   - Not suitable for production use without forking + stabilization

9. **Not Maintained**
   - This is a snapshot from AI Tinkerers talk
   - No ongoing support or updates
   - Fork for learning, not deployment

---

## Related Projects

### Core Dependencies

- **[garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana)** - Garmin Connect data synchronization to InfluxDB/Grafana
  - Required for Garmin integration
  - Provides InfluxDB backend that bot exports from

- **[OpenAI Agents](https://github.com/openai/openai-agents-python)** - Agent orchestration framework
  - Primary agent system for bot

- **[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)** - Telegram Bot API wrapper
  - Bot framework for all user interactions

### Inspiration & Related Work

- **[Obsidian](https://obsidian.md/)** - Knowledge base that works on local Markdown files
  - Core note-taking system for vault

- **[LangChain](https://github.com/langchain-ai/langchain)** - LLM application framework
  - Used for structured outputs and model abstraction

- **[ChromaDB](https://www.trychroma.com/)** - AI-native open-source embedding database
  - Powers semantic search across vault

---

## License

This project is licensed under the **Apache License 2.0**.

See [LICENSE](LICENSE) file for full text.

---

## Acknowledgments

- **[AI Tinkerers](https://aitinkerers.org/)** community for feedback, inspiration, and the opportunity to present this work
- **Arpit Anand** ([arpanghosh8453](https://github.com/arpanghosh8453)) for [garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana), which made Garmin integration practical
- All the open source projects this builds upon (see [Tech Stack](#tech-stack))
- The LLM community for developing agent frameworks, embedding models, and tools that made this project possible

---

**Built with ❤️ for personal use. Shared for learning.**

