from __future__ import annotations

from loguru import logger

from telegram_bot.config import ChromaVectorStoreConfig
from telegram_bot.service.scheduled_task_service import ScheduledTaskService

_TASK_ID = "obsidian_embedding_refresh"


def register_obsidian_embedding_refresh_task(
    scheduler: ScheduledTaskService,
    service_factory,
    config: ChromaVectorStoreConfig,
) -> None:
    """Register a nightly job that refreshes Obsidian embeddings."""

    if not config.refresh_enabled:
        logger.info("Obsidian embedding refresh disabled via configuration; skipping scheduler registration")
        return

    indexer = service_factory.obsidian_embedding_indexer

    async def _run_embedding_refresh() -> None:
        stats = await indexer.refresh_incremental()
        logger.info(
            "Obsidian embedding refresh finished: processed=%d skipped=%d deleted=%d chunks=%d",
            stats.processed_files,
            stats.skipped_files,
            stats.deleted_files,
            stats.upserted_chunks,
        )

    scheduler.add_job(
        cron_expression=config.refresh_cron,
        func=_run_embedding_refresh,
        job_id=_TASK_ID,
        display_name="Obsidian Embedding Refresh",
        description="Refreshes the semantic search index for Obsidian notes",
    )
