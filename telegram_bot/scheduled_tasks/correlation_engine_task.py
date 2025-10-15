from __future__ import annotations

from loguru import logger
from telegram import Bot

from telegram_bot.config import CorrelationEngineConfig
from telegram_bot.service.correlation_engine.job import CorrelationJobRunner
from telegram_bot.service.scheduled_task_service import ScheduledTaskService


class CorrelationEngineTask:
    """Registers the correlation engine job with the scheduler."""

    def __init__(
        self, config: CorrelationEngineConfig, job_runner: CorrelationJobRunner, bot: Bot, user_id: int
    ) -> None:
        self._config = config
        self._job_runner = job_runner
        self._bot = bot
        self._user_id = user_id

    def register_with_scheduler(self, scheduler: ScheduledTaskService) -> None:
        if not self._config.enabled:
            logger.info("Correlation engine task disabled; skipping scheduler registration")
            return

        async def _job() -> None:
            try:
                logger.info("🚀 Executing scheduled correlation engine job")
                summary = await self._job_runner.run()

                variance_alerts: list[str] = []
                variance_config = self._config.variance_analysis
                if summary.variance_results and variance_config.enabled:
                    alert_candidates = [variance for variance in summary.variance_results if variance.is_alert]
                    for variance in alert_candidates[: variance_config.max_alerts]:
                        variance_alerts.append(
                            f"  • {variance.raw_title} ({variance.metric.value}):"
                            f" Δ {variance.delta:.1f} | score {variance.normalised_score:.2f}"
                        )

                # Format and send success message
                if summary.results:
                    significant_correlations = [r for r in summary.results if r.triggered_metrics]

                    message_parts = [
                        "✅ Correlation analysis completed",
                        f"📊 Analyzed {len(summary.results)} events",
                        f"🔍 Found {len(significant_correlations)} events with significant correlations",
                        f"⏱ Window: {summary.window_days} days",
                    ]

                    if significant_correlations:
                        message_parts.append("\n🎯 Notable findings:")
                        for result in significant_correlations[:3]:  # Show top 3
                            event = result.event
                            metrics = ", ".join([m.metric.value for m in result.triggered_metrics])
                            message_parts.append(f"  • {event.title}: {metrics}")

                    if variance_alerts:
                        message_parts.append("\n📈 Variance alerts:")
                        message_parts.extend(variance_alerts)

                    message = "\n".join(message_parts)
                    logger.success(
                        "Correlation analysis completed: {} events with correlations", len(significant_correlations)
                    )
                else:
                    message = (
                        f"✅ Correlation analysis completed\n📊 No events found in the {summary.window_days}-day window"
                    )
                    logger.info("Correlation analysis completed with no events")

                await self._bot.send_message(chat_id=self._user_id, text=message, parse_mode=None)

            except Exception as e:
                error_message = f"❌ Correlation engine failed: {e}"
                logger.error("Correlation engine job failed: {}", e)
                logger.exception(e)
                try:
                    await self._bot.send_message(chat_id=self._user_id, text=error_message, parse_mode=None)
                except Exception as send_error:
                    logger.error("Failed to send error notification: {}", send_error)

        logger.info("Registering correlation engine task with schedule: {}", self._config.cron)
        scheduler.add_job(
            self._config.cron,
            _job,
            job_id="correlation_engine",
            display_name="Correlation Engine",
            description="Runs statistical correlation analysis across Garmin and calendar data.",
            metadata={
                "lookback_days": self._config.lookback_days,
                "timezone": self._config.timezone or "UTC",
            },
        )
        logger.info("Correlation engine task registered")
