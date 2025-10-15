# ChromaDB Integration Plan (updated for local embeddings + TDD)

## Goals
- Integrate ChromaDB as the semantic search backend for Obsidian Markdown notes.
- Store the persistent Chroma database under the bot `out_dir` (e.g. `<out_dir>/chroma`).
- Use local `SentenceTransformer` models for embedding generation (no remote APIs).
- Nightly at 03:00 refresh embeddings for all `.md` files in the vault.
- Apply LangChain `RecursiveCharacterTextSplitter` for chunking content before embedding.
- Expose a Telegram AI-assistant tool for semantically querying the vault.
- Provide manual CLI scripts for on-demand embedding refresh and semantic queries, with progress logging.
- Follow a strict TDD approach when implementing each component.

## Architectural Principles
- **Single Responsibility**: Separate concerns for vault access, chunking/embedding, vector-store persistence, scheduling, and assistant tooling.
- **Open/Closed**: Introduce abstractions (protocols/services) so alternative vector stores or chunking logic can be swapped without modifying high-level orchestration.
- **Liskov Substitution**: Depend on interfaces (`VectorStoreProtocol`) to allow drop-in replacements for Chroma if needed.
- **Interface Segregation**: Keep vector-store API narrow (`upsert`, `delete_missing`, `query`) tailored to indexer needs.
- **Dependency Inversion**: High-level services depend on abstractions; concrete dependencies (Chroma client, embedding function) are injected via `ServiceFactory` or config.

## High-Level Workstream
1. **Configuration & Dependencies**
   - Create `ChromaVectorStoreConfig` (persist dir defaulting to `<out_dir>/chroma`, collection name, sentence-transformer model name, batch sizes, cron schedule, toggles) in `telegram_bot/config.py`.
   - Extend `BotSettings` defaults and ensure serialization for scheduled jobs.
   - Confirm `chromadb`, `sentence-transformers`, and LangChain text splitter dependencies are installed via `uv`.

2. **Vector Store Abstraction Layer**
   - New package `telegram_bot/service/vector_store/` with:
     - `protocols.py` defining `VectorStoreProtocol`.
     - `chroma_vector_store.py` implementing Chroma client bootstrap (`Settings(persist_directory=<out_dir>/chroma)`), collection lifecycle, CRUD helpers, metadata schema, progress logging hook, and safe shutdown.
   - Expose factory to build local `SentenceTransformer` embeddings (downloading via HuggingFace as needed). Inject embedding callable so tests can substitute deterministic mocks.

3. **Obsidian Embedding Indexer Service**
   - Add `telegram_bot/service/obsidian/obsidian_embedding_service.py` with `ObsidianEmbeddingIndexer` that:
     - Uses `ObsidianService` (read-only transaction) to enumerate `.md` paths.
     - Leverages LangChain `RecursiveCharacterTextSplitter` (configurable chunk size/overlap) prior to embedding.
     - Hashes `(relative_path, chunk_index)` for stable IDs.
     - Captures metadata (`relative_path`, `title`, `mtime`, `checksum`) for change detection.
     - Performs incremental refresh (skip unchanged, delete missing) and full rebuild.
     - Provides `semantic_search(query, limit, filters)` returning scored snippets.
     - Emits structured progress logs (start/end, file counts, per-batch progress).

4. **Service Wiring**
   - Extend `ServiceFactory` with cached properties:
     - `chroma_vector_store` (configured from `BotSettings.chroma_vector_store`).
     - `obsidian_embedding_indexer` (inject `ObsidianService`, vector store, embeddings provider, timezone).
     - Optional `semantic_search_service` facade if needed by multiple consumers.
   - Ensure life-cycle management (lazy instantiation, reuse across tasks/tools).

5. **Nightly Scheduled Job**
   - Create `telegram_bot/scheduled_tasks/obsidian_embedding_task.py`:
     - Serialize config for pickle-safe execution (mirrors `morning_report_task`).
     - Sync function `refresh_obsidian_embeddings` to instantiate minimal dependencies and run `refresh_incremental` (using local embeddings and recursive splitter).
     - Optional `rebuild_obsidian_embeddings` entry point for full rebuild.
     - Async callback to log success/failure and optionally notify user via Telegram.
   - Register job in `register_scheduled_tasks` with cron `0 3 * * *`, respect `enabled` flag.
   - Add job id to `ScheduledTaskService` for manual triggering via existing facade.

6. **AI Assistant Semantic Search Tool**
   - Implement `telegram_bot/ai_assistant/tools/semantic_search_tool.py` with a `function_tool` binding to the indexer.
   - Tool signature: `(query: str, limit: int = 5, path_filter: str | None = None)` returning formatted matches (path, score, snippet).
   - Update `get_ai_assistant_agent` to register the tool (and related config in `AIAssistantConfig`).

7. **Manual CLI Scripts**
   - Add `tests/scripts/run_obsidian_embeddings.py` supporting subcommands:
     - `refresh` (incremental) and `rebuild` (full) – uses `asyncio.run` to invoke indexer, logs progress (files processed, chunk totals, elapsed time) to console.
     - `query --text "..." [--limit N] [--path-prefix ...]` executing semantic search and printing scored results (path, score, snippet).
   - Ensure script bootstraps `BotSettings`, builds `ServiceFactory`, and reuses configuration (persist dir under `out_dir/chroma`).
   - Include verbose logging (per-file progress, chunk counts, totals).

8. **Telemetry & Error Handling**
   - Add log context (e.g., `logger.bind(task="obsidian_embeddings")`).
   - Capture exceptions with actionable messages, ensure callbacks notify failure.
   - Optionally persist last run metadata (`out_dir/chroma_index_state.json`).

9. **Testing Strategy (TDD)**
   - Start every module with failing tests (unit first, then integration) before implementation.
   - Unit tests:
     - Mock vector store to validate `ObsidianEmbeddingIndexer` chunking (recursive splitter usage), diff detection, deletion path.
     - Ensure metadata stored (`relative_path`, `checksum`) drives incremental updates.
     - Test CLI argument parsing/execution (using `pytest` harness) with mocked services and progress logging assertions.
   - Integration tests (optional / offline): run against temp directory with dummy `.md` files and Chroma configured with temporary persist dir under tmp `out_dir`.
   - Inject fake embedding callable returning deterministic numpy arrays to keep tests fast and offline.

10. **Validation Checklist**
    - `uv run pytest` for new modules (ensuring newly added TDD tests pass).
    - Manual CLI run: `uv run python tests/scripts/run_obsidian_embeddings.py refresh --verbose`.
    - Manual CLI query: `uv run python tests/scripts/run_obsidian_embeddings.py query --text "..." --limit 5`.
    - Trigger scheduled job via `/scheduled_jobs` conversation or `ScheduledJobsFacade.run_job_now("obsidian_embedding_refresh")`.
    - Chatbot verification: ask assistant to run semantic search and confirm response includes relevant notes.

## Deliverables
- New config structures, services, scheduled task, and AI assistant tool wired into the existing architecture.
- CLI script with progress logging for manual embedding refresh/query.
- Tests ensuring indexer correctness and CLI behaviour.
- Documentation (this file) stored in `docs/`.

## Open Questions / Follow-ups
- Choose embedding function: reuse OpenAI, adopt local SentenceTransformers, or configure both via settings?
- Determine chunking strategy (length vs headings) and maximum tokens for search responses.
- Decide whether to cache embeddings locally for checkpointing between runs.
