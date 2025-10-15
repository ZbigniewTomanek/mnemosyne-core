from loguru import logger
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.db_service import DBService, FoodLogEntry

FOOD, PROTEIN, CARBS, FATS, COMMENT = range(5)
amount_reply_keyboard = [["High", "Medium", "Small"]]


class StartHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> int:
        await update.message.reply_text("🍽️ *FOOD LOGGING* 🍽️\n\n" "What did you eat? 🥙", parse_mode=ParseMode.MARKDOWN)
        return FOOD


class FoodHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> int:
        name = update.message.text
        if not name:
            await update.message.reply_text("❌ *Food name cannot be empty!*", parse_mode=ParseMode.MARKDOWN)
            return FOOD
        context.user_data["name"] = name
        await update.message.reply_text(
            "🥩 *Protein Content* 🥩\n\nHow much protein did this food contain?",
            reply_markup=ReplyKeyboardMarkup(
                amount_reply_keyboard,
                one_time_keyboard=True,
                input_field_placeholder="Protein content",
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return PROTEIN


class ProteinHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> int:
        protein = update.message.text
        if not protein:
            await update.message.reply_text("❌ *Protein content cannot be empty!*", parse_mode=ParseMode.MARKDOWN)
            return PROTEIN

        context.user_data["protein"] = protein
        await update.message.reply_text(
            "🍚 *Carbohydrate Content* 🍚\n\nHow many carbs did this food contain?",
            reply_markup=ReplyKeyboardMarkup(
                amount_reply_keyboard,
                one_time_keyboard=True,
                input_field_placeholder="Carbs content",
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return CARBS


class CarbsHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> int:
        carbs = update.message.text
        if not carbs:
            await update.message.reply_text("❌ *Carbs content cannot be empty!*", parse_mode=ParseMode.MARKDOWN)
            return CARBS

        context.user_data["carbs"] = carbs
        await update.message.reply_text(
            "🧈 *Fat Content* 🧈\n\nHow much fat did this food contain?",
            reply_markup=ReplyKeyboardMarkup(
                amount_reply_keyboard,
                one_time_keyboard=True,
                input_field_placeholder="Fats content",
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return FATS


class FatsHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> int:
        fats = update.message.text
        if not fats:
            await update.message.reply_text("❌ *Fat content cannot be empty!*", parse_mode=ParseMode.MARKDOWN)
            return FATS

        context.user_data["fats"] = fats
        await update.message.reply_text(
            "💬 *Additional Comments* 💬\n\nAny notes about this food? (type 'n' for none)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return COMMENT


class CommentHandler(PrivateHandler):
    def __init__(self, db_service: DBService):
        super().__init__()
        self.db_service = db_service

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        comment = update.message.text
        if comment.lower() == "n":
            comment = ""
        context.user_data["comment"] = comment
        self.db_service.add_food_log_entry(FoodLogEntry(**context.user_data))
        context.user_data.clear()
        await update.message.reply_text(
            "✅ *Food entry successfully logged!* ✅\n\nUse /list\\_food to view your food logs.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.message.from_user
    logger.info("User {} canceled the conversation.", user.first_name)
    await update.message.reply_text(
        "⚠️ *Food logging cancelled* ⚠️\n\nNo problem! You can start again anytime with /log\\_food.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


def get_food_log_handler(db_service: DBService) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("log_food", StartHandler().handle)],
        states={
            FOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, FoodHandler().handle)],
            PROTEIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ProteinHandler().handle)],
            CARBS: [MessageHandler(filters.TEXT & ~filters.COMMAND, CarbsHandler().handle)],
            FATS: [MessageHandler(filters.TEXT & ~filters.COMMAND, FatsHandler().handle)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, CommentHandler(db_service).handle)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
