#!/usr/bin/env python
"""Manual runner for the bio-signal correlation engine."""

import argparse
import asyncio
import sys

from loguru import logger

from telegram_bot import env_file_path  # noqa: F401 - ensures .env loading
from telegram_bot.config import BotSettings, CorrelationEngineConfig
from telegram_bot.service.correlation_engine.job import CorrelationJobRunner
from telegram_bot.service_factory import ServiceFactory


def _build_config(base: CorrelationEngineConfig, lookback_days: int | None) -> CorrelationEngineConfig:
    if lookback_days is None:
        return base
    return base.model_copy(update={"lookback_days": lookback_days})


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bio-signal correlation engine once")
    parser.add_argument("--lookback", type=int, default=None, help="Override lookback window in days")
    args = parser.parse_args()

    settings = BotSettings()
    services = ServiceFactory(settings)

    engine_config = _build_config(settings.correlation_engine, args.lookback)
    job_runner = CorrelationJobRunner(
        engine=services.correlation_engine,
        event_sources=[services.correlation_event_source, services.garmin_activity_event_source],
        config=engine_config,
        user_id=settings.my_telegram_user_id,
    )

    summary = await job_runner.run()
    if summary is None:
        logger.info("No correlation run executed (no events in range)")
        return

    logger.info("Correlation run {} completed with {} events", summary.run_id, len(summary.results))
    for result in summary.results:
        logger.info("Event: {} ({})", result.event.title, result.event.start)
        for effect in result.triggered_metrics:
            # Format p-value with scientific notation if very small
            p_value_str = f"{effect.p_value:.2e}" if effect.p_value < 0.001 else f"{effect.p_value:.4f}"
            logger.info(
                "  - {}: Δ={:.2f}, p={}, confidence={:.2f} (samples={})",
                effect.metric.value,
                effect.effect_size,
                p_value_str,
                effect.confidence,
                effect.sample_count,
            )

    if summary.variance_results:
        logger.info("\nVariance analysis ({} entries)", len(summary.variance_results))
        for variance in summary.variance_results[:10]:
            logger.info(
                "  • {} [{}]: baseline={:.2f}±{:.2f} (n={}) current={:.2f} Δ={:.2f} score={:.2f} {}",
                variance.raw_title,
                variance.metric.value,
                variance.baseline_mean,
                variance.baseline_stddev,
                variance.baseline_sample_count,
                variance.current_effect,
                variance.delta,
                variance.normalised_score,
                "⚠️" if variance.is_alert else "",
            )
    else:
        logger.info("\nVariance analysis skipped or no qualifying history")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    asyncio.run(main())
