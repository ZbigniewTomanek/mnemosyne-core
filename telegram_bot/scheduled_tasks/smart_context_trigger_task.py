from __future__ import annotations

from loguru import logger

from telegram_bot.service.context_trigger import ContextTriggerExecutor


class SmartContextTriggerTask:
    """
    A scheduled task wrapper that delegates to ContextTriggerService.

    Follows Single Responsibility Principle: only responsible for being a scheduled task wrapper.
    The actual logic is in ContextTriggerService to maintain separation of concerns.
    """

    def __init__(self, trigger_executor: ContextTriggerExecutor):
        self.trigger_executor = trigger_executor
        self.trigger_name = trigger_executor.config.name
        logger.info(f"Initialized SmartContextTriggerTask: {self.trigger_name}")

    async def run(self) -> None:
        """Execute the context trigger analysis via the service."""
        try:
            logger.debug(f"🚀 Starting scheduled execution of trigger: {self.trigger_name}")
            await self.trigger_executor.run()
            logger.debug(f"✅ Completed scheduled execution of trigger: {self.trigger_name}")
        except Exception as e:
            logger.error(f"❌ Error in scheduled trigger task {self.trigger_name}: {e}")
            logger.exception(e)
