from __future__ import annotations

from types import SimpleNamespace

import pytest

from telegram_bot.config import ChromaVectorStoreConfig


class StubScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(
        self, cron_expression, func, args=(), kwargs=None, *, job_id, display_name, description=None, metadata=None
    ):
        self.jobs.append(
            {
                "cron": cron_expression,
                "func": func,
                "args": args,
                "kwargs": kwargs or {},
                "job_id": job_id,
                "display_name": display_name,
                "description": description,
                "metadata": metadata,
            }
        )


class StubIndexer:
    def __init__(self):
        self.calls = 0

    async def refresh_incremental(self):
        self.calls += 1
        return SimpleNamespace(
            processed_files=1,
            skipped_files=0,
            deleted_files=0,
            upserted_chunks=1,
        )


@pytest.mark.asyncio
async def test_registers_refresh_job_when_enabled():
    from telegram_bot.scheduled_tasks.obsidian_embedding_task import register_obsidian_embedding_refresh_task

    scheduler = StubScheduler()
    indexer = StubIndexer()
    config = ChromaVectorStoreConfig(refresh_enabled=True, refresh_cron="0 3 * * *")
    service_factory = SimpleNamespace(obsidian_embedding_indexer=indexer)

    register_obsidian_embedding_refresh_task(scheduler, service_factory, config)

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job["cron"] == "0 3 * * *"
    assert job["job_id"] == "obsidian_embedding_refresh"

    await job["func"]()
    assert indexer.calls == 1


@pytest.mark.asyncio
async def test_skips_registration_when_disabled():
    from telegram_bot.scheduled_tasks.obsidian_embedding_task import register_obsidian_embedding_refresh_task

    scheduler = StubScheduler()
    indexer = StubIndexer()
    config = ChromaVectorStoreConfig(refresh_enabled=False)
    service_factory = SimpleNamespace(obsidian_embedding_indexer=indexer)

    register_obsidian_embedding_refresh_task(scheduler, service_factory, config)

    assert scheduler.jobs == []
