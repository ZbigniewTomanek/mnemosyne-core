import asyncio
from typing import Optional

from telegram_bot.config import BotSettings
from telegram_bot.service.context_trigger import ContextAnalyzerService, ContextTriggerExecutor
from telegram_bot.service.llm_service import LLMService
from telegram_bot.service_factory import ServiceFactory


class MockBot:
    async def send_message(self, chat_id: int, text: str, parse_mode: Optional[str] = None):
        header = f"[MOCK BOT] chat_id={chat_id} parse_mode={parse_mode}"
        print(header)
        print(text)
        print("---")


async def main():
    config = BotSettings()
    mock_bot = MockBot()

    service_factory = ServiceFactory(config)
    test_config = list(config.context_trigger_task_config.values())[-1]
    context_trigger_service = ContextTriggerExecutor(
        config=test_config,
        obsidian_service=service_factory.obsidian_service,
        aggregator=service_factory.context_aggregator,
        telegram_bot=mock_bot,
        user_id=124,
        tz=config.tz,
        analyzer=ContextAnalyzerService(LLMService(test_config.llm_config)),
    )

    await context_trigger_service.run()


if __name__ == "__main__":
    asyncio.run(main())
