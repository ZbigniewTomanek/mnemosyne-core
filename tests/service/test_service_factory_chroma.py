from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from telegram_bot.ai_assistant.agents.ai_assitant_agent import AIAssistantConfig
from telegram_bot.config import BotSettings, ChromaVectorStoreConfig, ObsidianConfig, WhisperSettings
from telegram_bot.service_factory import ServiceFactory


class FakeSentenceTransformer:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def encode(self, texts, show_progress_bar: bool = False, normalize_embeddings: bool = False):
        return [[float(len(text))] for text in texts]


class FakeSentenceTransformerEmbeddingFunction:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = FakeSentenceTransformer(model_name)

    def __call__(self, input):
        embeddings = self._model.encode(list(input), show_progress_bar=False, normalize_embeddings=True)
        return embeddings

    def name(self) -> str:
        return f"FakeSentenceTransformer({self._model_name})"


class FakeChromaStore:
    instances: list["FakeChromaStore"] = []

    def __init__(self, config: ChromaVectorStoreConfig, embedding_function, out_dir, client=None):
        self.config = config
        self.embedding_function = embedding_function
        self.out_dir = out_dir
        self.client = client
        self.upserts: list[Any] = []
        FakeChromaStore.instances.append(self)

    def upsert(self, documents):
        self.upserts.append(list(documents))


class FakeEmbeddingIndexer:
    instances: list["FakeEmbeddingIndexer"] = []

    def __init__(self, obsidian_service, vector_store, config, out_dir, text_splitter=None, state_path=None):
        self.obsidian_service = obsidian_service
        self.vector_store = vector_store
        self.config = config
        self.out_dir = out_dir
        self.text_splitter = text_splitter
        FakeEmbeddingIndexer.instances.append(self)


class FakeObsidianService:
    def __init__(self, config):
        self.config = config


@pytest.fixture(autouse=True)
def stub_sentence_transformer(monkeypatch):
    sys.modules.pop("sentence_transformers", None)
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    )
    yield
    sys.modules.pop("sentence_transformers", None)


@pytest.fixture(autouse=True)
def stub_dependencies(monkeypatch):
    monkeypatch.setattr("telegram_bot.service_factory.ChromaVectorStore", FakeChromaStore)
    monkeypatch.setattr("telegram_bot.service_factory.ObsidianEmbeddingIndexer", FakeEmbeddingIndexer)
    monkeypatch.setattr("telegram_bot.service_factory.ObsidianService", FakeObsidianService)
    monkeypatch.setattr(
        "telegram_bot.service_factory.SentenceTransformerEmbeddingFunction",
        FakeSentenceTransformerEmbeddingFunction,
    )
    yield
    FakeChromaStore.instances.clear()
    FakeEmbeddingIndexer.instances.clear()


@pytest.fixture
def bot_settings(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    vault_dir = tmp_path / "vault"
    (vault_dir / ".git").mkdir(parents=True, exist_ok=True)

    settings = BotSettings(
        telegram_bot_api_key="dummy",
        my_telegram_user_id=1,
        out_dir=out_dir,
        whisper=WhisperSettings(model_size="tiny"),
        ai_assistant=AIAssistantConfig(),
        obsidian_config=ObsidianConfig(obsidian_root_dir=vault_dir),
        chroma_vector_store=ChromaVectorStoreConfig(embedding_model_name="fake-model"),
    )
    return settings


def test_service_factory_builds_shared_vector_store(bot_settings):
    factory = ServiceFactory(bot_settings)

    indexer = factory.obsidian_embedding_indexer
    vector_store = factory.chroma_vector_store

    assert indexer is FakeEmbeddingIndexer.instances[0]
    assert vector_store is FakeChromaStore.instances[0]
    assert indexer.vector_store is vector_store
    assert vector_store.config is bot_settings.chroma_vector_store

    embedding_output = vector_store.embedding_function(["alpha", "beta"])
    assert embedding_output == [[5.0], [4.0]]
