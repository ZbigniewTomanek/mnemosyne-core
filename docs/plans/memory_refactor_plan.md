# Persistent Memory Refactor Plan

## Objective
Create a structured, context-aware persistent memory system that keeps the Obsidian knowledge base accurate, deduplicated, and easy to maintain while staying testable and compliant with SOLID principles.

## Document Format & Section Design
- Preserve YAML frontmatter with keys such as `consolidation_type`, `last_updated`, and `tags`.
- Introduce fixed second-level headings (`##`) for each domain: `Zdrowie i Samopoczucie`, `Praca i Produktywność`, `Relacje i Kontakty`, `Hobby i Zainteresowania`, `Projekty Osobiste`, `Finanse`, `Systemy i Narzędzia`, `Podróże`.
- Under every heading, store facts inside a Markdown table with columns: `id`, `statement`, `category`, `confidence`, `first_seen`, `last_seen`, `sources`, `status`, `notes`.
- Choose Markdown tables because they are human readable, diff-friendly, and deterministic to parse.
- Generate `id` values automatically (e.g., deterministic hashes) to keep provenance stable while allowing manual edits to other columns.
- Provide a configurable mapping from LLM-extracted fact categories to these sections so routing can evolve without touching core logic.

## Domain Model & Services
- Create a `PersistentFact` value object capturing the table columns and comparison helpers (including auto-generated identifiers).
- Represent each section with a `PersistentSection` aggregate that knows how to parse/render its table and evaluate changes.
- Wrap the entire document in a `PersistentMemoryDocument` aggregate that maintains the frontmatter, section order, and round-trip Markdown conversion.
- Place the new types in a dedicated module such as `telegram_bot/service/persistent_memory/` and expose pure, side-effect-free parsing/rendering utilities to simplify unit testing.

## Update Workflow Refactor
- Replace `_update_persistent_memory` in `telegram_bot/scheduled_tasks/memory_consolidation_task.py` with an injected `PersistentMemoryUpdater` that orchestrates read → diff → write.
- The updater should:
  - Load the existing document (if present) into the domain model.
  - Map new LLM facts into sections, matching against existing records by `statement`/`category` (or explicit `id` when supplied) to detect updates.
  - Calculate per-section deltas: facts to add, to update (e.g., new confidence, timestamps, sources), and to remove when the LLM marks them obsolete.
  - Render the updated document back to Markdown and write it through the Obsidian service.
  - Emit a structured delta summary for observability and debugging.
- Add configuration fields to `MemoryConsolidationTaskConfig` for thresholds (confidence minimum, section routing overrides) and inject them into the updater so the consolidation flow remains declarative.
- Ensure `telegram_bot/service/llm_service.py` exposes an interface for structured responses describing fact deltas (e.g., `PersistentMemoryDelta`), so consolidation runs receive typed results instead of raw JSON.

## LLM Context Usage
- Keep `LifeContextService` responsibilities unchanged; it should continue to supply persistent memory content as part of the context bundle for prompts (see `docs/ai_assistant_fetch_context_plan.md`).
- Because the document itself is already human readable, no additional parsing is required in life-context formatting—callers can embed relevant sections directly in prompts when needed.

## Testing Strategy
- Unit tests for parser/render symmetry across frontmatter and all sections, including malformed inputs and manual edits.
- Tests for section mapping logic and delta computation covering add/update/remove scenarios, conflicting metadata, and unknown categories.
- Asynchronous integration tests around `_run_consolidation_logic` using fixture Obsidian services to ensure the scheduler wires up the updater correctly.
- Formatter tests that validate Markdown output and confirm token budgeting still works with the structured persistent memory payload.

## Confirmed Decisions
- Fact identifiers are auto-generated to maintain stable references while keeping Obsidian edits simple.
- Obsolescence of facts is determined entirely by the LLM output; no grace period logic is required in code.
- Historical append-only files will be migrated manually once the new implementation is ready, so no automated backfill step is needed.
