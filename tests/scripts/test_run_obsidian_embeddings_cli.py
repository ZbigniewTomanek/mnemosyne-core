from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from telegram_bot.service.vector_store.protocols import VectorMatch


class StubIndexer:
    def __init__(self):
        self.incremental_calls = 0
        self.full_calls = 0
        self.query_calls: list[tuple[str, int, str | None]] = []

    async def refresh_incremental(self):
        self.incremental_calls += 1
        return SimpleNamespace(processed_files=2, skipped_files=1, deleted_files=0, upserted_chunks=4)

    async def refresh_full(self):
        self.full_calls += 1
        return SimpleNamespace(processed_files=5, skipped_files=0, deleted_files=1, upserted_chunks=20)

    async def semantic_search(self, query: str, *, limit: int = 5, path_filter: str | None = None):
        self.query_calls.append((query, limit, path_filter))
        return [VectorMatch(id="note1::0", score=0.12, content="Chunk text", metadata={"relative_path": "note1.md"})]


@pytest.fixture
def fake_run():
    def runner(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return runner


@pytest.fixture
def script_module(monkeypatch, fake_run):
    from tests.scripts import run_obsidian_embeddings as script

    indexer = StubIndexer()
    factory = SimpleNamespace(obsidian_embedding_indexer=indexer)

    monkeypatch.setattr(script, "build_service_factory", lambda: factory)
    monkeypatch.setattr(script, "_run", fake_run)

    return script, indexer


def test_refresh_invokes_incremental(script_module, capsys):
    script, indexer = script_module

    exit_code = script.main(["refresh"])

    assert exit_code == 0
    assert indexer.incremental_calls == 1
    captured = capsys.readouterr().out
    assert "Processed files: 2" in captured


def test_rebuild_invokes_full_refresh(script_module, capsys):
    script, indexer = script_module

    exit_code = script.main(["rebuild"])

    assert exit_code == 0
    assert indexer.full_calls == 1
    captured = capsys.readouterr().out
    assert "Deleted files: 1" in captured


def test_query_prints_formatted_results(script_module, capsys):
    script, indexer = script_module

    exit_code = script.main(["query", "--text", "focus", "--limit", "1"])

    assert exit_code == 0
    assert indexer.query_calls == [("focus", 1, None)]
    output = capsys.readouterr().out
    assert "note1.md" in output
    assert "0.12" in output
