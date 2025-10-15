from typing import Any

from telegram import Update
from telegram.ext import CallbackContext, MessageHandler, filters

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.ai_assitant_service import AIAssistantService
from telegram_bot.utils import send_message_chunks


class DefaultMessageHandler(PrivateHandler):
    def __init__(self, ai_assistant_service: AIAssistantService):
        super().__init__()
        self.ai_assistant_service = ai_assistant_service

    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        user_id = update.effective_user.id
        message_text = update.message.text

        # Process the message with AI Assistant
        response = await self.ai_assistant_service.run_ai_assistant(user_id=user_id, query=message_text)

        # Send response using chunked message function
        await send_message_chunks(context.bot, update.effective_chat.id, response)


def get_default_message_handler(ai_assistant_service: AIAssistantService) -> MessageHandler:
    return MessageHandler(filters.TEXT & ~filters.COMMAND, DefaultMessageHandler(ai_assistant_service).handle)
