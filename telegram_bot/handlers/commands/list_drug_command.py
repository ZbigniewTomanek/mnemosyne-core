from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.db_service import DBService


class ListDrugHandler(PrivateHandler):
    def __init__(self, db_service: DBService) -> None:
        super().__init__()
        self.db_service = db_service

    async def _handle(self, update: Update, context: CallbackContext) -> None:
        limit = context.args[0] if context.args else 10
        reply = ["💊 *MEDICATION LOG* 💊\n"]

        drug_logs = self.db_service.list_drug_logs(limit)
        if not drug_logs:
            reply.append("_No medication entries found. Use /log\\_drug to add some!_")
        else:
            for log_entry in drug_logs:
                reply.append(
                    f"🕒 `{log_entry.datetime}` - *{log_entry.drug_name}*\n" f"📊 Dosage: `{log_entry.dosage}`\n"
                )

        await update.message.reply_text("\n".join(reply), parse_mode=ParseMode.MARKDOWN)


def get_list_drugs_command(db_service: DBService) -> CommandHandler:
    return CommandHandler("list_drugs", ListDrugHandler(db_service).handle)
