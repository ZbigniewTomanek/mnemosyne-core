from datetime import datetime
from typing import Any

from agents import Agent, Runner
from loguru import logger

from telegram_bot.ai_assistant.agents.ai_assitant_agent import get_ai_assistant_agent
from telegram_bot.config import BotSettings
from telegram_bot.service.db_service import DBService, MessageEntry, MessageType
from telegram_bot.service.life_context.service import LifeContextService
from telegram_bot.service.obsidian.obsidian_daily_notes_manager import ObsidianDailyNotesManager
from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer
from telegram_bot.utils import clean_ai_response


class AIAssistantService:
    def __init__(
        self,
        db_service: DBService,
        bot_settings: BotSettings,
        obsidian_daily_notes_manager: ObsidianDailyNotesManager,
        life_context_service: LifeContextService,
        obsidian_embedding_indexer: ObsidianEmbeddingIndexer,
    ) -> None:
        self.db_service = db_service
        self.bot_settings = bot_settings
        self.ai_assistant_agent: Agent[Any] | None = None
        self.obsidian_daily_notes_manager = obsidian_daily_notes_manager
        self.life_context_service = life_context_service
        self.obsidian_embedding_indexer = obsidian_embedding_indexer

    async def run_ai_assistant(self, user_id: int, query: str, message_type: MessageType = MessageType.TEXT) -> str:
        if self.ai_assistant_agent is None:
            logger.info(f"Initializing AI Assistant agent for user {user_id}")
            self.ai_assistant_agent = await get_ai_assistant_agent(
                self.bot_settings.ai_assistant,
                log_file_path=self.bot_settings.out_dir / self.bot_settings.ai_assistant.relative_log_dir,
                obsidian_daily_notes_manager=self.obsidian_daily_notes_manager,
                life_context_service=self.life_context_service,
                tz=self.bot_settings.tz,
                embedding_indexer=self.obsidian_embedding_indexer,
            )

        recent_messages = list(
            self.db_service.list_message_logs(user_id=user_id, limit=self.bot_settings.ai_assistant.last_n_messages)
        )

        conversation_context = ""
        if recent_messages:
            lines = ["Previous conversation:"]
            for msg in reversed(recent_messages):  # Display oldest to newest
                lines.append(f"User: {msg.content}")
                lines.append(f"Assistant: {msg.response}")
                lines.append("")
            if lines[-1] == "":  # Drop trailing spacer
                lines.pop()
            lines.append("Current message:")
            conversation_context = "\n".join(lines)

        # Build the complete query with context and timestamp
        full_query = f"{conversation_context}{query}\n\nToday is {datetime.now().isoformat()}"

        logger.debug(f"Running AI Assistant for user {user_id} with query including context")
        result = await Runner.run(
            self.ai_assistant_agent, input=full_query, max_turns=self.bot_settings.ai_assistant.max_turns
        )
        final_output = clean_ai_response(result.final_output)
        logger.debug(f"AI Assistant response: {final_output}")

        # Save just the original query in the database, not the full context
        message_entry = MessageEntry(user_id=user_id, message_type=message_type, content=query, response=final_output)
        self.db_service.add_message_entry(message_entry)
        return final_output
