import os
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger
from telegram import Update
from telegram.ext import CallbackContext


class PrivateHandler(ABC):
    def __init__(self) -> None:
        user_id = os.getenv("MY_TELEGRAM_USER_ID")
        if user_id is None:
            raise ValueError("MY_TELEGRAM_USER_ID is not set in .env file")
        self.user_id = int(user_id)

    async def handle(self, update: Update, context: CallbackContext) -> Any:
        logger.debug(
            f"Received message {update.message.text} from {update.effective_user.name}(id: {update.effective_user.id})"
        )
        if update.effective_user.id != self.user_id:
            await update.message.reply_text("Fuck off dude 😎")
            return
        try:
            return await self._handle(update, context)
        except Exception as e:
            await update.message.reply_text(f"Exception has occurred!\n{e}")
            logger.exception(e)

    @abstractmethod
    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        raise NotImplementedError
