from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

from telegram_bot.config import ChromaVectorStoreConfig
from telegram_bot.service.vector_store.protocols import VectorDocument


@pytest.fixture(autouse=True)
def stub_chromadb(monkeypatch):
    sys.modules.pop("chromadb", None)
    sys.modules.pop("chromadb.config", None)

    collection_mock = Mock()
    client_mock = Mock()
    client_mock.get_or_create_collection.return_value = collection_mock

    persistent_client_ctor = Mock(return_value=client_mock)
    settings_ctor = Mock()

    chromadb_module = ModuleType("chromadb")
    chromadb_module.PersistentClient = persistent_client_ctor
    chromadb_module.config = ModuleType("chromadb.config_proxy")

    config_module = ModuleType("chromadb.config")
    config_module.Settings = settings_ctor

    monkeypatch.setitem(sys.modules, "chromadb", chromadb_module)
    monkeypatch.setitem(sys.modules, "chromadb.config", config_module)

    yield {
        "collection": collection_mock,
        "client": client_mock,
        "persistent_client_ctor": persistent_client_ctor,
        "settings_ctor": settings_ctor,
    }

    sys.modules.pop("chromadb", None)
    sys.modules.pop("chromadb.config", None)


def import_chroma_store():
    module = importlib.import_module("telegram_bot.service.vector_store.chroma_vector_store")
    importlib.reload(module)
    return module


def test_initialises_persistent_client_with_resolved_path(stub_chromadb):
    chroma_module = import_chroma_store()
    embedding_fn = Mock(name="embedding_fn")
    config = ChromaVectorStoreConfig()
    out_dir = Path("/tmp/out")

    chroma_module.ChromaVectorStore(config=config, embedding_function=embedding_fn, out_dir=out_dir)

    settings_ctor = stub_chromadb["settings_ctor"]
    persistent_client_ctor = stub_chromadb["persistent_client_ctor"]

    settings_ctor.assert_called_once()
    kwargs = settings_ctor.call_args.kwargs
    assert kwargs["persist_directory"] == str(config.resolve_persist_path(out_dir))
    persistent_client_ctor.assert_called_once_with(settings=settings_ctor.return_value)


def test_upsert_sends_documents_to_collection(stub_chromadb):
    chroma_module = import_chroma_store()
    collection = stub_chromadb["collection"]
    embedding_fn = Mock(name="embedding_fn")
    config = ChromaVectorStoreConfig(collection_name="notes")
    store = chroma_module.ChromaVectorStore(config=config, embedding_function=embedding_fn, out_dir=Path("/tmp/out"))

    docs = [
        VectorDocument(id="doc-1", content="First", metadata={"path": "note1.md"}),
        VectorDocument(id="doc-2", content="Second", metadata={"path": "note2.md"}),
    ]

    store.upsert(docs)

    collection.upsert.assert_called_once_with(
        ids=["doc-1", "doc-2"],
        documents=["First", "Second"],
        metadatas=[{"path": "note1.md"}, {"path": "note2.md"}],
    )


def test_delete_missing_removes_stale_documents(stub_chromadb):
    chroma_module = import_chroma_store()
    collection = stub_chromadb["collection"]
    collection.get.return_value = {"ids": ["keep", "stale"]}
    store = chroma_module.ChromaVectorStore(
        config=ChromaVectorStoreConfig(collection_name="notes"),
        embedding_function=Mock(),
        out_dir=Path("/tmp/out"),
    )

    store.delete_missing(valid_ids={"keep"})

    collection.delete.assert_called_once_with(ids=["stale"])


def test_query_returns_vector_matches(stub_chromadb):
    chroma_module = import_chroma_store()
    collection = stub_chromadb["collection"]
    collection.query.return_value = {
        "ids": [["doc-1", "doc-2"]],
        "distances": [[0.05, 0.2]],
        "documents": [["chunk 1", "chunk 2"]],
        "metadatas": [[{"path": "note1.md"}, {"path": "note2.md"}]],
    }
    store = chroma_module.ChromaVectorStore(
        config=ChromaVectorStoreConfig(),
        embedding_function=Mock(),
        out_dir=Path("/tmp/out"),
    )

    results = store.query("hello world", limit=2)

    assert len(results) == 2
    assert results[0].id == "doc-1"
    # Score is converted from distance: 1/(1+0.05) = 0.9523809523809523
    assert results[0].score == pytest.approx(1.0 / (1.0 + 0.05))
    assert results[0].metadata["path"] == "note1.md"
    collection.query.assert_called_once_with(
        query_texts=["hello world"],
        n_results=2,
        where=None,
        include=["metadatas", "documents", "distances"],
    )
