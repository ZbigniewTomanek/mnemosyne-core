#!/usr/bin/env python3
"""
Garmin Connect export conversation handler for the Telegram bot.

This module provides the conversation handler for exporting Garmin Connect data.
"""

import datetime as dt
import json
import tempfile
from pathlib import Path

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from telegram_bot.handlers.base.public_handler import PublicHandler
from telegram_bot.service.garmin_connect_service import GarminConnectService

# Conversation states
FORMAT, PERIOD, CUSTOM_START, CUSTOM_END = range(4)


class GarminExportHandler(PublicHandler):
    """
    Handler for the Garmin Connect data export conversation.
    """

    def __init__(self, garmin_service: GarminConnectService) -> None:
        """
        Initialize the handler with a GarminConnectService.

        Args:
            garmin_service: The GarminConnectService to use for data export.
        """
        super().__init__()
        self.garmin_service = garmin_service

    async def start_export(self, update: Update, context: CallbackContext) -> int:
        """
        Start the data export conversation.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        user_id = update.effective_user.id

        # Check if user is authenticated
        if not self.garmin_service.account_manager.is_authenticated(user_id):
            await update.message.reply_text(
                "You need to connect your Garmin account first. Use /connect\\_garmin to get started."
            )
            return ConversationHandler.END

        # Create inline keyboard with export format options
        keyboard = [
            [InlineKeyboardButton("Markdown Report", callback_data="format_markdown")],
            [InlineKeyboardButton("Aggregated JSON", callback_data="format_aggregated_json")],
            [InlineKeyboardButton("Raw JSON", callback_data="format_raw_json")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("Please select an export format:", reply_markup=reply_markup)
        return FORMAT

    async def select_format(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the format selection from the user.

        Args:
            update: The update containing the callback query.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        query = update.callback_query
        await query.answer()

        selected_format = query.data.replace("format_", "")
        context.user_data["export_format"] = selected_format

        logger.info(f"User {update.effective_user.id} selected format: {selected_format}")

        # Create inline keyboard with period options
        keyboard = [
            [InlineKeyboardButton("Last 7 days", callback_data="period_7")],
            [InlineKeyboardButton("Last 14 days", callback_data="period_14")],
            [InlineKeyboardButton("Last 30 days", callback_data="period_30")],
            [InlineKeyboardButton("Custom period", callback_data="period_custom")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text("Please select a time period:", reply_markup=reply_markup)
        return PERIOD

    async def select_period(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the period selection from the user.

        Args:
            update: The update containing the callback query.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        query = update.callback_query
        await query.answer()

        selected_period = query.data.replace("period_", "")
        logger.info(f"User {update.effective_user.id} selected period: {selected_period}")

        # Handle custom period separately
        if selected_period == "custom":
            await query.edit_message_text("Please enter the start date in YYYY-MM-DD format:")
            return CUSTOM_START

        # Calculate date range for predefined periods
        days = int(selected_period)
        end_date = dt.datetime.now().date()
        start_date = end_date - dt.timedelta(days=days - 1)

        context.user_data["start_date"] = start_date
        context.user_data["end_date"] = end_date

        # Generate and send the export
        await query.edit_message_text(
            f"Generating {context.user_data['export_format']} export for the last {days} days..."
        )

        await self._generate_and_send_export(update, context)
        return ConversationHandler.END

    async def receive_custom_start_date(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the custom start date input from the user.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        start_date_str = update.message.text
        try:
            start_date = dt.date.fromisoformat(start_date_str)
            context.user_data["start_date"] = start_date

            await update.message.reply_text("Please enter the end date in YYYY-MM-DD format:")
            return CUSTOM_END
        except ValueError:
            await update.message.reply_text("Invalid date format. Please enter the start date in YYYY-MM-DD format:")
            return CUSTOM_START

    async def receive_custom_end_date(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the custom end date input from the user.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        end_date_str = update.message.text
        try:
            end_date = dt.date.fromisoformat(end_date_str)
            start_date = context.user_data["start_date"]

            # Validate date range
            if end_date < start_date:
                await update.message.reply_text("End date must be after start date. Please enter a valid end date:")
                return CUSTOM_END

            # Check if date range is too long
            if (end_date - start_date).days > 90:
                await update.message.reply_text(
                    "Date range is too long (maximum 90 days). Please enter a closer end date:"
                )
                return CUSTOM_END

            context.user_data["end_date"] = end_date

            await update.message.reply_text(
                f"Generating {context.user_data['export_format']} export for "
                f"{start_date.isoformat()} to {end_date.isoformat()}..."
            )

            await self._generate_and_send_export(update, context)
            return ConversationHandler.END

        except ValueError:
            await update.message.reply_text("Invalid date format. Please enter the end date in YYYY-MM-DD format:")
            return CUSTOM_END

    async def _generate_and_send_export(self, update: Update, context: CallbackContext) -> None:
        """
        Generate and send the export based on the selected format and date range.

        Args:
            update: The update containing the message or callback query.
            context: The callback context.
        """
        user_id = update.effective_user.id
        selected_format = context.user_data["export_format"]
        start_date = context.user_data["start_date"]
        end_date = context.user_data["end_date"]

        logger.info(f"Generating {selected_format} export for user {user_id} from {start_date} to {end_date}")

        try:
            # Generate the appropriate export based on format
            if selected_format == "markdown":
                await self._send_markdown_export(update, context, user_id, start_date, end_date)
            elif selected_format == "aggregated_json":
                await self._send_aggregated_json_export(update, context, user_id, start_date, end_date)
            elif selected_format == "raw_json":
                await self._send_raw_json_export(update, context, user_id, start_date, end_date)

        except Exception as e:
            logger.exception(f"Error generating export: {e}")

            # Determine the appropriate method to send the error message
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"❌ Error generating export: {str(e)}\n\nPlease try again later."
                )
            else:
                await update.message.reply_text(f"❌ Error generating export: {str(e)}\n\nPlease try again later.")

    async def _send_markdown_export(
        self, update: Update, context: CallbackContext, user_id: int, start_date: dt.date, end_date: dt.date
    ) -> None:
        """
        Generate and send a markdown export.

        Args:
            update: The update containing the message or callback query.
            context: The callback context.
            user_id: The user ID to generate the export for.
            start_date: The start date for the export.
            end_date: The end date for the export.
        """
        report = await self.garmin_service.generate_markdown_report(
            user_id, start_date, end_date, days=(end_date - start_date).days + 1
        )

        # For markdown, send as a text message if small enough, otherwise as a file
        if len(report) < 4000:
            if update.callback_query:
                await context.bot.send_message(user_id, report, parse_mode="Markdown")
                await update.callback_query.edit_message_text("✅ Export completed!")
            else:
                await context.bot.send_message(user_id, report, parse_mode="Markdown")
                await update.message.reply_text("✅ Export completed!")
        else:
            # Create temp file and send as document
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
                temp_path.write_text(report)

                filename = f"garmin_report_{start_date.isoformat()}_{end_date.isoformat()}.md"

                with open(temp_path, "rb") as file:
                    await context.bot.send_document(user_id, document=file, filename=filename)

                # Delete the temp file
                temp_path.unlink(missing_ok=True)

                if update.callback_query:
                    await update.callback_query.edit_message_text("✅ Export completed!")
                else:
                    await update.message.reply_text("✅ Export completed!")

    async def _send_aggregated_json_export(
        self, update: Update, context: CallbackContext, user_id: int, start_date: dt.date, end_date: dt.date
    ) -> None:
        """
        Generate and send an aggregated JSON export.

        Args:
            update: The update containing the message or callback query.
            context: The callback context.
            user_id: The user ID to generate the export for.
            start_date: The start date for the export.
            end_date: The end date for the export.
        """
        data = await self.garmin_service.export_aggregated_json(
            user_id, start_date, end_date, days=(end_date - start_date).days + 1
        )

        # Create temp file and send as document
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            temp_path.write_text(json.dumps(data, indent=2))

            filename = f"garmin_data_{start_date.isoformat()}_{end_date.isoformat()}.json"

            with open(temp_path, "rb") as file:
                await context.bot.send_document(user_id, document=file, filename=filename)

            # Delete the temp file
            temp_path.unlink(missing_ok=True)

            if update.callback_query:
                await update.callback_query.edit_message_text("✅ Export completed!")
            else:
                await update.message.reply_text("✅ Export completed!")

    async def _send_raw_json_export(
        self, update: Update, context: CallbackContext, user_id: int, start_date: dt.date, end_date: dt.date
    ) -> None:
        """
        Generate and send a raw JSON export.

        Args:
            update: The update containing the message or callback query.
            context: The callback context.
            user_id: The user ID to generate the export for.
            start_date: The start date for the export.
            end_date: The end date for the export.
        """
        data = await self.garmin_service.export_raw_json(
            user_id, start_date, end_date, days=(end_date - start_date).days + 1
        )

        # Create temp file and send as document
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            temp_path.write_text(json.dumps(data, indent=2))

            filename = f"garmin_raw_{start_date.isoformat()}_{end_date.isoformat()}.json"

            with open(temp_path, "rb") as file:
                await context.bot.send_document(user_id, document=file, filename=filename)

            # Delete the temp file
            temp_path.unlink(missing_ok=True)

            if update.callback_query:
                await update.callback_query.edit_message_text("✅ Export completed!")
            else:
                await update.message.reply_text("✅ Export completed!")

    async def cancel(self, update: Update, context: CallbackContext) -> int:
        """
        Cancel the export conversation.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The end of conversation.
        """
        await update.message.reply_text("Export cancelled.")
        return ConversationHandler.END

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the command that starts the export conversation.

        This is the entry point for the conversation when used as a standalone handler.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        return await self.start_export(update, context)


def get_garmin_export_handler(garmin_service: GarminConnectService) -> ConversationHandler:
    """
    Returns a conversation handler for Garmin Connect data export.

    Args:
        garmin_service: The GarminConnectService to use for data export.

    Returns:
        A ConversationHandler configured for the data export flow.
    """
    handler = GarminExportHandler(garmin_service)

    return ConversationHandler(
        entry_points=[CommandHandler("garmin_export", handler.handle)],
        states={
            FORMAT: [CallbackQueryHandler(handler.select_format, pattern=r"^format_")],
            PERIOD: [CallbackQueryHandler(handler.select_period, pattern=r"^period_")],
            CUSTOM_START: [
                CommandHandler("cancel", handler.cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_custom_start_date),
            ],
            CUSTOM_END: [
                CommandHandler("cancel", handler.cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_custom_end_date),
            ],
        },
        fallbacks=[CommandHandler("cancel", handler.cancel)],
    )
