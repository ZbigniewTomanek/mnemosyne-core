from abc import ABC, abstractmethod
from typing import Any

from loguru import logger
from telegram import Update
from telegram.ext import CallbackContext


class PublicHandler(ABC):
    async def handle(self, update: Update, context: CallbackContext) -> Any:
        logger.debug(
            f"Received message {update.message.text} from {update.effective_user.name}(id: {update.effective_user.id})"
        )
        try:
            return await self._handle(update, context)
        except Exception as e:
            await update.message.reply_text(f"Exception has occurred!\n{e}")
            logger.exception(e)

    @abstractmethod
    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        raise NotImplementedError
