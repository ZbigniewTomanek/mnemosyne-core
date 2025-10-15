from __future__ import annotations

from typing import Final

from loguru import logger
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler, ConversationHandler, MessageHandler, filters

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.scheduled_jobs_facade import ScheduledJobsFacade
from telegram_bot.service.scheduled_task_service import ScheduledJobDescriptor
from telegram_bot.utils import escape_markdown_v1

SELECT_JOB, CONFIRM_RUN = range(2)
JOB_MAPPING_KEY: Final[str] = "scheduled_jobs_mapping"
SELECTED_JOB_KEY: Final[str] = "scheduled_selected_job"

RUN_TILE = "🚀 Run now"
BACK_TILE = "⬅️ Back"
EXIT_TILE = "❌ Exit"


def _build_keyboard_tiles(descriptors: list[ScheduledJobDescriptor]) -> list[list[str]]:
    tiles: list[str] = []
    for index, descriptor in enumerate(descriptors, start=1):
        tiles.append(f"{index}. {descriptor.display_name}")

    keyboard: list[list[str]] = []
    row: list[str] = []
    for tile in tiles:
        row.append(tile)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([EXIT_TILE])
    return keyboard


def _format_job_tile(descriptor: ScheduledJobDescriptor) -> str:
    description = descriptor.description or "No description provided."
    metadata_lines = []
    for key, value in descriptor.metadata.items():
        metadata_lines.append(f"• *{key}*: `{value}`")
    metadata_block = "\n".join(metadata_lines)
    if metadata_block:
        metadata_block = f"\n{metadata_block}"

    return (
        f"*{descriptor.display_name}*\n"
        f"🕒 Schedule: `{descriptor.schedule}`\n"
        f"🆔 ID: `{descriptor.job_id}`\n"
        f"{description}{metadata_block}"
    )


class ScheduledJobsStartHandler(PrivateHandler):
    def __init__(self, facade: ScheduledJobsFacade) -> None:
        super().__init__()
        self._facade = facade

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        descriptors = list(self._facade.list_jobs())
        if not descriptors:
            await update.message.reply_text(
                "⚠️ No scheduled jobs are currently registered.", reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END

        context.user_data[JOB_MAPPING_KEY] = {
            f"{index}. {descriptor.display_name}": descriptor.job_id
            for index, descriptor in enumerate(descriptors, start=1)
        }

        tiles_keyboard = ReplyKeyboardMarkup(
            _build_keyboard_tiles(descriptors),
            one_time_keyboard=False,
            resize_keyboard=True,
            input_field_placeholder="Select a job to inspect",
        )

        tile_descriptions = [
            f"{index}. *{descriptor.display_name}*\n   _{descriptor.schedule}_"
            for index, descriptor in enumerate(descriptors, start=1)
        ]

        await update.message.reply_text(
            "🗓️ *Scheduled Jobs*\n\nSelect a job tile below to view details and optionally run it now.\n\n"
            + "\n".join(tile_descriptions),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tiles_keyboard,
        )
        return SELECT_JOB


class ScheduledJobsSelectionHandler(PrivateHandler):
    def __init__(self, facade: ScheduledJobsFacade) -> None:
        super().__init__()
        self._facade = facade

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        selection = update.message.text
        mapping = context.user_data.get(JOB_MAPPING_KEY, {})

        if selection == EXIT_TILE:
            await update.message.reply_text("✅ Exiting scheduled jobs menu.", reply_markup=ReplyKeyboardRemove())
            context.user_data.pop(JOB_MAPPING_KEY, None)
            context.user_data.pop(SELECTED_JOB_KEY, None)
            return ConversationHandler.END

        job_id = mapping.get(selection)
        if not job_id:
            await update.message.reply_text("❌ Unknown tile. Please pick a scheduled job from the keyboard.")
            return SELECT_JOB

        descriptor = self._facade.get_job(job_id)
        if descriptor is None:
            logger.warning("Scheduled job %s no longer present when user selected tile.", job_id)
            await update.message.reply_text("⚠️ This job is no longer available. Please select another one.")
            mapping.pop(selection, None)
            return SELECT_JOB

        context.user_data[SELECTED_JOB_KEY] = descriptor.job_id

        confirm_keyboard = ReplyKeyboardMarkup(
            [[RUN_TILE], [BACK_TILE, EXIT_TILE]],
            one_time_keyboard=False,
            resize_keyboard=True,
        )

        await update.message.reply_text(
            _format_job_tile(descriptor),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=confirm_keyboard,
        )
        return CONFIRM_RUN


class ScheduledJobsRunHandler(PrivateHandler):
    def __init__(self, facade: ScheduledJobsFacade) -> None:
        super().__init__()
        self._facade = facade

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        text = update.message.text
        if text == BACK_TILE:
            logger.debug("User requested to go back to scheduled jobs list.")
            return await ScheduledJobsStartHandler(self._facade).handle(update, context)

        if text == EXIT_TILE:
            await update.message.reply_text("✅ Exiting scheduled jobs menu.", reply_markup=ReplyKeyboardRemove())
            context.user_data.pop(JOB_MAPPING_KEY, None)
            context.user_data.pop(SELECTED_JOB_KEY, None)
            return ConversationHandler.END

        if text != RUN_TILE:
            await update.message.reply_text(
                "❌ Please choose *Run now*, *Back*, or *Exit*.", parse_mode=ParseMode.MARKDOWN
            )
            return CONFIRM_RUN

        job_id = context.user_data.get(SELECTED_JOB_KEY)
        if not job_id:
            await update.message.reply_text("⚠️ No job selected. Returning to job list.")
            return await ScheduledJobsStartHandler(self._facade).handle(update, context)

        outcome = await self._facade.run_job_now(job_id)
        status_icon = "✅" if outcome.success else "❌"

        # Escape markdown special characters in dynamic content to prevent parsing errors
        escaped_message = escape_markdown_v1(outcome.message)

        try:
            # Try sending with markdown first
            await update.message.reply_text(
                f"{status_icon} *{outcome.display_name}*\n\n{escaped_message}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception as e:
            # If markdown fails, fall back to plain text to ensure user gets feedback
            logger.error(f"Failed to send markdown message for job {job_id}: {e}. Falling back to plain text.")
            try:
                await update.message.reply_text(
                    f"{status_icon} {outcome.display_name}\n\n{outcome.message}",
                    reply_markup=ReplyKeyboardRemove(),
                )
            except Exception as e:
                # Log if even plain text fails, but still cleanup state
                logger.exception(f"Failed to send plain text message for job {job_id}: {e}")
        finally:
            # CRITICAL: Always cleanup conversation state, even if message sending fails
            # This prevents the user from getting stuck in CONFIRM_RUN state
            context.user_data.pop(JOB_MAPPING_KEY, None)
            context.user_data.pop(SELECTED_JOB_KEY, None)

        return ConversationHandler.END


async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("❌ Scheduled jobs conversation cancelled.", reply_markup=ReplyKeyboardRemove())
    context.user_data.pop(JOB_MAPPING_KEY, None)
    context.user_data.pop(SELECTED_JOB_KEY, None)
    return ConversationHandler.END


def get_scheduled_jobs_handler(facade: ScheduledJobsFacade) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("scheduled_jobs", ScheduledJobsStartHandler(facade).handle)],
        states={
            SELECT_JOB: [MessageHandler(filters.TEXT & ~filters.COMMAND, ScheduledJobsSelectionHandler(facade).handle)],
            CONFIRM_RUN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ScheduledJobsRunHandler(facade).handle)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
