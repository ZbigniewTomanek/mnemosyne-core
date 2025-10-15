from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest

from telegram_bot.config import ChromaVectorStoreConfig
from telegram_bot.service.vector_store.protocols import VectorDocument, VectorMatch, VectorStoreProtocol


@dataclass
class _QueryCall:
    query_text: str
    limit: int
    where: Mapping[str, object] | None


class StubVectorStore(VectorStoreProtocol):
    def __init__(self) -> None:
        self.upsert_calls: list[list[VectorDocument]] = []
        self.delete_missing_calls: list[set[str]] = []
        self.query_calls: list[_QueryCall] = []
        self.query_results: Sequence[VectorMatch] = []

    def upsert(self, documents: Sequence[VectorDocument]) -> None:
        self.upsert_calls.append(list(documents))

    def delete_missing(self, valid_ids: Iterable[str]) -> None:
        self.delete_missing_calls.append(set(valid_ids))

    def query(
        self,
        query_text: str,
        limit: int = 5,
        where: Mapping[str, object] | None = None,
    ) -> Sequence[VectorMatch]:
        self.query_calls.append(_QueryCall(query_text, limit, where))
        return self.query_results


class StubObsidianService:
    def __init__(self, root_dir: Path) -> None:
        self.config = SimpleNamespace(obsidian_root_dir=root_dir)

    async def safe_read_file(self, relative_path: str) -> str:
        absolute_path = self.config.obsidian_root_dir / relative_path
        return absolute_path.read_text(encoding="utf-8")


class SimpleSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def create_documents(self, texts: Sequence[str], metadatas: Sequence[Mapping[str, object]] | None = None):
        chunks = []
        for text in texts:
            start = 0
            index = 0
            while start < len(text):
                end = start + self.chunk_size
                chunk_text = text[start:end]
                chunks.append(SimpleNamespace(page_content=chunk_text, metadata={"chunk_index": index, "start": start}))
                start += (
                    self.chunk_size - self.chunk_overlap if self.chunk_size > self.chunk_overlap else self.chunk_size
                )
                index += 1
        return chunks


@pytest.fixture
def splitter():
    return SimpleSplitter(chunk_size=100, chunk_overlap=20)


@pytest.fixture
def obsidian_setup(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note1.md").write_text("# Note One\nContent for the first note.", encoding="utf-8")
    (vault / "note2.md").write_text("# Note Two\nSome other content.", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return vault, out_dir


@pytest.mark.asyncio
async def test_refresh_incremental_processes_changed_files(obsidian_setup, splitter):
    from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer

    vault, out_dir = obsidian_setup
    vector_store = StubVectorStore()
    service = StubObsidianService(vault)
    config = ChromaVectorStoreConfig(chunk_size=splitter.chunk_size, chunk_overlap=splitter.chunk_overlap)
    indexer = ObsidianEmbeddingIndexer(
        obsidian_service=service,
        vector_store=vector_store,
        config=config,
        out_dir=out_dir,
        text_splitter=splitter,
    )

    await indexer.refresh_incremental()
    assert len(vector_store.upsert_calls) == 1
    assert {doc.id for doc in vector_store.upsert_calls[0]} == {
        "note1.md::chunk-0",
        "note2.md::chunk-0",
    }

    await indexer.refresh_incremental()
    assert len(vector_store.upsert_calls) == 1, "Unchanged files should not trigger new upserts"

    (vault / "note2.md").write_text("# Note Two\nSome other content. Updated!", encoding="utf-8")
    await asyncio.sleep(0.01)  # ensure mtime changes

    await indexer.refresh_incremental()
    assert len(vector_store.upsert_calls) == 2
    assert {doc.id for doc in vector_store.upsert_calls[-1]} == {"note2.md::chunk-0"}


@pytest.mark.asyncio
async def test_refresh_incremental_deletes_removed_files(obsidian_setup, splitter):
    from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer

    vault, out_dir = obsidian_setup
    vector_store = StubVectorStore()
    service = StubObsidianService(vault)
    config = ChromaVectorStoreConfig(chunk_size=splitter.chunk_size, chunk_overlap=splitter.chunk_overlap)
    indexer = ObsidianEmbeddingIndexer(
        obsidian_service=service,
        vector_store=vector_store,
        config=config,
        out_dir=out_dir,
        text_splitter=splitter,
    )

    await indexer.refresh_incremental()
    assert vector_store.delete_missing_calls[-1] == {"note1.md::chunk-0", "note2.md::chunk-0"}

    (vault / "note1.md").unlink()
    await asyncio.sleep(0.01)

    await indexer.refresh_incremental()
    assert vector_store.delete_missing_calls[-1] == {"note2.md::chunk-0"}


@pytest.mark.asyncio
async def test_semantic_search_delegates_to_vector_store(obsidian_setup, splitter):
    from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer

    vault, out_dir = obsidian_setup
    vector_store = StubVectorStore()
    vector_store.query_results = [
        VectorMatch(id="doc-1", score=0.1, content="chunk", metadata={"relative_path": "note1.md"})
    ]
    service = StubObsidianService(vault)
    config = ChromaVectorStoreConfig(chunk_size=splitter.chunk_size, chunk_overlap=splitter.chunk_overlap)
    indexer = ObsidianEmbeddingIndexer(
        obsidian_service=service,
        vector_store=vector_store,
        config=config,
        out_dir=out_dir,
        text_splitter=splitter,
    )

    results = await indexer.semantic_search("hello", limit=3, path_filter="note1.md")
    assert results == vector_store.query_results
    assert vector_store.query_calls[-1] == _QueryCall("hello", 3, {"relative_path": "note1.md"})


@pytest.mark.asyncio
async def test_metadata_contains_expected_fields(obsidian_setup, splitter):
    from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer

    vault, out_dir = obsidian_setup
    vector_store = StubVectorStore()
    service = StubObsidianService(vault)
    config = ChromaVectorStoreConfig(chunk_size=splitter.chunk_size, chunk_overlap=splitter.chunk_overlap)
    indexer = ObsidianEmbeddingIndexer(
        obsidian_service=service,
        vector_store=vector_store,
        config=config,
        out_dir=out_dir,
        text_splitter=splitter,
    )

    await indexer.refresh_incremental()
    first_call = vector_store.upsert_calls[0]
    metadata = {doc.id: doc.metadata for doc in first_call}

    note_meta = metadata["note1.md::chunk-0"]
    assert note_meta["relative_path"] == "note1.md"
    assert note_meta["title"] == "Note One"
    assert "checksum" in note_meta
    assert "mtime" in note_meta

    state_path = out_dir / "chroma_index_state.json"
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "note1.md" in saved_state["files"]
