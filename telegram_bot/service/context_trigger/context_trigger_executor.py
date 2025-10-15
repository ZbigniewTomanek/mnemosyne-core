from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from telegram_bot.service.context_trigger.context_aggregator import ContextAggregator
from telegram_bot.service.context_trigger.context_analyzer_service import ContextAnalyzerService
from telegram_bot.service.context_trigger.models import ContextTriggerConfig, TriggerAnalysisResult, TriggerPrio
from telegram_bot.service.obsidian.obsidian_service import ObsidianService
from telegram_bot.utils import send_message_chunks


class ContextTriggerExecutor:
    """High-level orchestrator: gathers context, analyzes it, and executes triggers."""

    def __init__(
        self,
        config: ContextTriggerConfig,
        aggregator: ContextAggregator,
        analyzer: ContextAnalyzerService,
        obsidian_service: ObsidianService,
        telegram_bot,
        user_id: int,
        tz: ZoneInfo,
    ) -> None:
        self.config = config
        self.aggregator = aggregator
        self.analyzer = analyzer
        self.obsidian_service = obsidian_service
        self.telegram_bot = telegram_bot
        self.user_id = user_id
        self.tz = tz

        logger.info(f"Initialized TriggerExecutor: {self.config.name}")

    async def run(self) -> None:
        """Run the full trigger flow with robust error handling."""
        try:
            logger.info(f"🔍 Running context trigger: {self.config.name}")
            context_data = await self.aggregator.gather_context(self.config)
            analysis = await self.analyzer.analyze(self.config, context_data)

            if analysis.should_trigger:
                logger.info(f"✅ Trigger activated: {self.config.name} (confidence: {analysis.confidence})")
                await self._send_success_message(analysis)
            else:
                logger.debug(f"⏸️ Trigger not activated: {self.config.name}")
        except Exception as e:
            logger.exception(f"❌ Error in context trigger {self.config.name}: {e}")
            await self._send_failure_message(e)

    async def _send_success_message(self, analysis: TriggerAnalysisResult) -> None:
        if not analysis.suggested_message:
            logger.warning(f"No message provided for trigger {self.config.name}")
            return

        priority_emoji = {
            TriggerPrio.LOW: "💡",
            TriggerPrio.NORMAL: "🔔",
            TriggerPrio.HIGH: "⚠️",
            TriggerPrio.URGENT: "🚨",
        }
        emoji = priority_emoji.get(analysis.priority, "🔔")

        formatted_message = (
            f"{emoji} **{self.config.name}**\n\n"
            f"{analysis.suggested_message}\n\n"
            f"_Confidence: {analysis.confidence:.0%}_"
        )

        await send_message_chunks(self.telegram_bot, self.user_id, formatted_message)
        logger.success(f"✅ Sent trigger message for {self.config.name}")

        # Log to Obsidian AI log
        today = datetime.now(tz=self.tz).date()
        await self.obsidian_service.add_ai_log_entry(
            today, f"Smart Context Trigger: {self.config.name}\n{formatted_message}", "context_trigger"
        )

    async def _send_failure_message(self, error: Exception) -> None:
        try:
            msg = f"🚨 Trigger '{self.config.name}' failed to run."
            await send_message_chunks(self.telegram_bot, self.user_id, msg)
        except Exception as send_err:
            logger.error(f"Failed to notify user about trigger failure: {send_err}")
