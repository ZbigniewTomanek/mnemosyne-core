from typing import Any

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.bot_restart_service import BotRestartService


class BotRestartHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        """
        Handle the /restart command.

        Args:
            update: The update containing the message.
            context: The callback context.
        """
        await update.message.reply_text("🔄 *Restarting bot...* 🔄")
        BotRestartService.restart()


def get_restart_command() -> CommandHandler:
    return CommandHandler("restart", BotRestartHandler().handle)
