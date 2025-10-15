from __future__ import annotations

from telegram_bot.config import CorrelationEngineConfig
from telegram_bot.service.correlation_engine.models import BioSignalType


def test_correlation_engine_config_includes_variance_config_defaults():
    config = CorrelationEngineConfig()

    job_config = config.to_job_config()

    variance_cfg = job_config.variance_analysis
    assert variance_cfg.enabled is True
    assert variance_cfg.lookback_days == 30
    assert variance_cfg.min_samples == 3
    assert variance_cfg.min_score_for_alert == 1.0
    assert variance_cfg.max_alerts == 3


def test_correlation_engine_config_to_job_config_copies_sources_and_sleep_config():
    config = CorrelationEngineConfig()
    sources = config.sources.model_copy(deep=True)
    sources.calendar.enabled = False
    sleep_cfg = config.sleep_analysis.model_copy(deep=True)
    sleep_cfg.enabled = False
    config = config.model_copy(update={"sources": sources, "sleep_analysis": sleep_cfg})

    job_config = config.to_job_config()

    assert job_config.sources.calendar.enabled is False
    assert job_config.sleep_analysis.enabled is False

    # Mutating job config should not affect base configuration
    job_config.sources.calendar.enabled = True
    job_config.sleep_analysis.enabled = True

    assert config.sources.calendar.enabled is False
    assert config.sleep_analysis.enabled is False


def test_correlation_engine_config_respects_metric_enable_flags():
    config = CorrelationEngineConfig()
    config.metrics[BioSignalType.STRESS].enabled = False

    job_config = config.to_job_config()

    assert BioSignalType.STRESS not in job_config.metrics
    assert BioSignalType.BODY_BATTERY in job_config.metrics
