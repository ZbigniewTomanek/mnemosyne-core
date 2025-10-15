# Project Plan: Bio-Signal Correlation Engine

### 1. Introduction & Goal

- **1.1. Vision:** Deliver an always-on personal health data scientist that automatically aligns Garmin bio-signals with
  life context from notes, calendar, and conversations to surface high-signal correlations and actionable
  recommendations inside Obsidian.
- **1.2. Problem Statement:** Users collect rich physiological metrics and qualitative context, but lack a trustworthy
  way to uncover hidden drivers behind stress, sleep quality, or recovery; the engine addresses this gap by turning raw
  traces into interpretable, proactive insights.
- **1.3. Success Criteria:**
    - Generate at least one high-confidence (confidence ≥ 0.7, samples ≥ 3) correlation insight per rolling week, stored
      in Obsidian with supporting evidence.
    - Deliver automated Obsidian reports (daily or weekly) that summarize correlations with traceable links to source
      notes, calendar events, and Garmin metrics.
    - Maintain correlation processing latency under 30 minutes for a 7-day analysis window, running unattended via
      scheduled tasks.

### 2. Synthesized Project Context

- **2.1. Existing Architecture:**
    - `ScheduledTaskService` and `BackgroundTaskExecutor` already orchestrate cron-style jobs (morning report, memory
      consolidation), providing the scaffolding for a nightly Bio-Signal correlation job.
    - `ObsidianService` and `ObsidianDailyNotesManager` offer safe, lock-aware vault writes plus note templating,
      enabling structured correlation and entity notes with `[[wikilinks]]` and YAML frontmatter.
    - `LLMService` supplies structured extraction and summarization pipelines reused for entity detection, correlation
      narrative generation, and suggestion drafting.
    - Garmin integration via `InfluxDBGarminDataExporter` and related services exposes pandas-ready DataFrames (stress,
      HRV, body battery, sleep) that can be aligned with contextual timelines.
    - The AI assistant stack and persistent memory pipeline already push insights back into Obsidian and Telegram,
      allowing correlation outputs to flow into conversational experiences or proactive nudges.
- **2.2. Key Data Inputs:**
    - **Garmin Data:** Time-series exports for stress, Body Battery, HRV, sleep summary/intraday, heart rate, steps,
      breathing rate, and activities sourced through the InfluxDB exporter for configurable day ranges.
    - **Events Data:** Calendar events (title, start/end, attendees) pulled via AppleScript automations and Garmin
      activity sessions/laps that timestamp workouts or runs.
    - **Qualitative Data:** Daily notes, AI reflections, persistent memory facts, and entity-rich documents in Obsidian
      that capture people, projects, tasks, and contextual summaries.
    - **Location Data:** Potential AppleScript-driven collection of meeting or reminder locations plus GPS metadata
      embedded in Garmin activities for geographic correlation.

### 3. Proposed Development Roadmap (Phased Approach)

#### **Phase 1: Foundational MVP - Event Correlation**

- **Objective:** Validate end-to-end correlation flows by linking scheduled events to short-term physiological
  responses.
- **Key Activities:**
    - Implement a nightly scheduled job that fetches the past 7 days of calendar events and Garmin stress/body
      battery/heart-rate intraday series, reusing the existing exporter and scheduler.
    - Build deterministic time alignment utilities (e.g., pandas reindex/resample) to compare post-event 3-hour windows
      against daily baselines and surface deltas above configurable thresholds.
    - Produce an Obsidian Markdown summary (`BioSignal Reports/weekly.md`) highlighting notable stress deltas with
      direct links to the originating events and publish via Telegram once per week.
- **Expected Outcome:** Demonstrated ability to answer questions such as "How does my average stress level change after
  my weekly team meeting?" with reproducible, data-backed reports.

#### **Phase 2: Deep Context Integration**

- **Objective:** Enrich correlations by tying physiological metrics to qualitative context (people, projects, locations)
  for more personalized insights.
- **Key Activities:**
    - Extend the scheduled pipeline to call `LLMService` for named-entity extraction over daily notes and AI
      reflections, storing structured entity snapshots alongside timestamps.
    - Expand correlation logic to join entity occurrences and location cues with daily bio-signal aggregates (stress,
      sleep score, Body Battery change), comparing against rolling baselines and recording sample sizes.
    - Upgrade Obsidian reporting to embed correlation cards with `[[wikilinks]]` to relevant entity notes, daily logs,
      and location pages, plus metadata (effect size, confidence, sample count).
- **Expected Outcome:** Insights such as "Days mentioning [[Projects/Alpha]] show a 15% higher average stress and 10%
  lower sleep score than baseline," enabling targeted reviews of specific relationships.

#### **Phase 3: Predictive & Proactive Insights**

- **Objective:** Transition from descriptive analytics to proactive guidance by adding statistical rigor, longitudinal
  storage, and alerting.
- **Key Activities:**
    - Incorporate statistical significance tests (e.g., Welch’s t-test via `scipy.stats`) and effect-size thresholds to
      filter correlations, persisting results in a dedicated Obsidian "Correlation Index" directory with YAML metadata.
    - Track correlation history to detect strengthening/weakening trends, updating or archiving insights accordingly and
      exposing them to the persistent memory service.
    - Integrate the correlation index with proactive notification flows (morning reports, Telegram nudges) that warn
      about upcoming high-impact events and recommend mitigations.
- **Expected Outcome:** A mature engine that not only reports past patterns but also anticipates risk scenarios—for
  example, "You have a meeting with [[People/Alex]] today; prior occurrences correlated with 35% higher stress. Schedule
  a decompression walk afterward."

### 4. Summary & Next Steps

| Phase   | Objective                                               | Complexity                                                        | Insight Quality                           |
|---------|---------------------------------------------------------|-------------------------------------------------------------------|-------------------------------------------|
| Phase 1 | Correlate events with immediate bio-signal shifts       | Low – reuses existing schedulers and data exports                 | Basic, event-level comparisons            |
| Phase 2 | Fuse qualitative context and locations with bio-signals | Medium – adds entity extraction, richer joins, enhanced reporting | Contextual, multi-entity narratives       |
| Phase 3 | Provide statistically-backed, proactive recommendations | High – introduces significance testing, indexing, alerting        | High-confidence, forward-looking guidance |

Recommended to begin with Phase 1. Immediate next steps:

- Inventory available Garmin and calendar datasets, defining the canonical schema for MVP alignment.
- Draft pandas transformation utilities and baselining strategy for stress/body battery windows.
- Prepare an Obsidian report template and scheduler wiring to run the MVP job on a controlled 7-day backlog.
