from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.db_service import DBService


class ListFoodHandler(PrivateHandler):
    def __init__(self, db_service: DBService) -> None:
        super().__init__()
        self.db_service = db_service

    async def _handle(self, update: Update, context: CallbackContext) -> None:
        limit = context.args[0] if context.args else 10
        reply = ["🍽️ *YOUR FOOD LOG* 🍽️\n"]

        food_logs = self.db_service.list_food_logs(limit)
        if not food_logs:
            reply.append("_No food entries found. Use /log_food to add some!_")
        else:
            for food_log_entry in food_logs:
                reply.append(
                    f"🕒 `{food_log_entry.datetime}` - *{food_log_entry.name}*\n"
                    f"🥩 Protein: `{food_log_entry.protein}g`\n"
                    f"🍚 Carbs: `{food_log_entry.carbs}g`\n"
                    f"🧈 Fats: `{food_log_entry.fats}g`\n"
                    f"💬 _{food_log_entry.comment or 'No comment'}_\n"
                )

        await update.message.reply_text("\n".join(reply), parse_mode=ParseMode.MARKDOWN)


def get_list_food_command(db_service: DBService) -> CommandHandler:
    return CommandHandler("list_food", ListFoodHandler(db_service).handle)
