from pathlib import Path

import pytest

from telegram_bot.ai_assistant.agents.ai_assitant_agent import AIAssistantConfig
from telegram_bot.config import BotSettings, ChromaVectorStoreConfig, WhisperSettings


@pytest.fixture()
def minimal_bot_settings_kwargs():
    return {
        "telegram_bot_api_key": "dummy-token",
        "my_telegram_user_id": 123,
        "whisper": WhisperSettings(model_size="tiny"),
        "ai_assistant": AIAssistantConfig(),
    }


def test_bot_settings_exposes_chroma_config(minimal_bot_settings_kwargs):
    settings = BotSettings(**minimal_bot_settings_kwargs)
    assert isinstance(settings.chroma_vector_store, ChromaVectorStoreConfig)


def test_chroma_persist_path_defaults_to_out_dir_subdir(minimal_bot_settings_kwargs):
    out_dir = Path("/tmp/custom-out")
    settings = BotSettings(out_dir=out_dir, **minimal_bot_settings_kwargs)
    resolved_path = settings.chroma_vector_store.resolve_persist_path(settings.out_dir)
    assert resolved_path == out_dir / settings.chroma_vector_store.persist_relative_dir


def test_override_persist_relative_dir(minimal_bot_settings_kwargs):
    out_dir = Path("/tmp/custom-out")
    settings = BotSettings(
        out_dir=out_dir,
        chroma_vector_store=ChromaVectorStoreConfig(persist_relative_dir=Path("alt")),
        **minimal_bot_settings_kwargs,
    )
    resolved_path = settings.chroma_vector_store.resolve_persist_path(settings.out_dir)
    assert resolved_path == out_dir / Path("alt")


def test_default_refresh_cron_is_3_am(minimal_bot_settings_kwargs):
    settings = BotSettings(**minimal_bot_settings_kwargs)
    assert settings.chroma_vector_store.refresh_cron == "0 3 * * *"


def test_default_embedding_model(minimal_bot_settings_kwargs):
    settings = BotSettings(**minimal_bot_settings_kwargs)
    assert settings.chroma_vector_store.embedding_model_name.startswith("sentence-transformers/")
