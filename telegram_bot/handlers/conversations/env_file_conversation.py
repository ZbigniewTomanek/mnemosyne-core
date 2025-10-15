#!/usr/bin/env python3
"""
Environment variable file conversation handlers for the Telegram bot.

This module provides conversation handlers for reading and setting environment
variables using file uploads/downloads when values are too long for regular messages.
"""

import io
import json
from pathlib import Path
from typing import Any

from loguru import logger
from telegram import Document, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler, ConversationHandler, MessageHandler, filters

from telegram_bot.handlers.base.private_handler import PrivateHandler

# Conversation states
WAITING_FOR_FILE = 1

# Telegram message size limits
MAX_MESSAGE_LENGTH = 4000  # Conservative limit to account for formatting


class ReadEnvFileHandler(PrivateHandler):
    """Handler for reading environment variables and sending long values as files."""

    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        """Read a specific environment variable value and send as file if too long."""
        if not context.args:
            await update.message.reply_text("❌ Please provide a variable name: /read_env_file VARIABLE_NAME")
            return

        var_name = context.args[0]
        env_file = Path(".env")

        if not env_file.exists():
            await update.message.reply_text("❌ No .env file found")
            return

        try:
            with open(env_file, "r") as f:
                lines = f.readlines()

            for line in lines:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() == var_name:
                        # Check if value is too long for a regular message
                        if len(value) > MAX_MESSAGE_LENGTH:
                            # Send as file
                            file_content = value.encode("utf-8")
                            file_obj = io.BytesIO(file_content)
                            file_obj.name = f"{var_name}.txt"

                            await update.message.reply_document(
                                document=file_obj,
                                filename=f"{var_name}.txt",
                                caption=f"📄 Value for environment variable `{var_name}`\n\n"
                                f"💾 File size: {len(file_content)} bytes",
                                parse_mode=ParseMode.MARKDOWN,
                            )
                        else:
                            # Send as regular message
                            await update.message.reply_text(f"🔍 {var_name}={value}")
                        return

            await update.message.reply_text(f"❌ Variable '{var_name}' not found in .env file")

        except Exception as e:
            logger.error(f"Error reading .env file: {e}")
            await update.message.reply_text(f"❌ Error reading .env file: {str(e)}")


class SetEnvFileStartHandler(PrivateHandler):
    """Handler to start the file-based environment variable setting conversation."""

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        """Start the conversation for setting an environment variable from a file."""
        if not context.args:
            await update.message.reply_text("❌ Please provide a variable name: /set_env_file VARIABLE_NAME")
            return ConversationHandler.END

        var_name = context.args[0]
        context.user_data["env_var_name"] = var_name

        await update.message.reply_text(
            f"📁 *SET ENVIRONMENT VARIABLE FROM FILE* 📁\n\n"
            f"Variable: `{var_name}`\n\n"
            f"📤 Please upload a text file containing the value for this environment variable.\n\n"
            f"📋 Supported formats:\n"
            f"• Plain text files (.txt)\n"
            f"• JSON files (.json)\n"
            f"• Any text-based file\n\n"
            f"⚠️ *File size limit: 20MB*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_FOR_FILE


class SetEnvFileReceiveHandler(PrivateHandler):
    """Handler to receive and process the uploaded file for environment variable setting."""

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        """Process the uploaded file and set the environment variable."""
        var_name = context.user_data.get("env_var_name")
        if not var_name:
            await update.message.reply_text("❌ Session expired. Please start again with /set_env_file")
            return ConversationHandler.END

        document: Document = update.message.document
        if not document:
            await update.message.reply_text("❌ Please upload a file, or use /cancel to abort.")
            return WAITING_FOR_FILE

        try:
            # Check file size (Telegram API limit is 20MB)
            if document.file_size > 20 * 1024 * 1024:
                await update.message.reply_text("❌ File too large. Maximum size is 20MB.")
                return WAITING_FOR_FILE

            # Download the file
            file = await document.get_file()
            file_content = await file.download_as_bytearray()

            # Decode the content as text
            try:
                var_value = file_content.decode("utf-8").strip()
            except UnicodeDecodeError:
                await update.message.reply_text("❌ File must contain valid UTF-8 text.")
                return WAITING_FOR_FILE

            # Handle JSON formatting if the file appears to be JSON
            if document.file_name and document.file_name.endswith(".json"):
                try:
                    # Validate and format JSON
                    parsed_value = json.loads(var_value)
                    var_value = json.dumps(parsed_value)
                except json.JSONDecodeError as e:
                    await update.message.reply_text(f"❌ Invalid JSON format: {str(e)}")
                    return WAITING_FOR_FILE

            # Update the .env file
            env_file = Path(".env")

            # Read existing lines
            lines = []
            if env_file.exists():
                with open(env_file, "r") as f:
                    lines = f.readlines()

            # Look for existing variable and update it
            found = False
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
                    key = line_stripped.split("=", 1)[0].strip()
                    if key == var_name:
                        lines[i] = f"{var_name}={var_value}\n"
                        found = True
                        break

            # If variable not found, append it
            if not found:
                if lines and not lines[-1].endswith("\n"):
                    lines.append("\n")
                lines.append(f"{var_name}={var_value}\n")

            # Write back to file
            with open(env_file, "w") as f:
                f.writelines(lines)

            # Success message with summary
            value_preview = var_value[:100] + "..." if len(var_value) > 100 else var_value
            await update.message.reply_text(
                f"✅ *Environment variable updated successfully!* ✅\n\n"
                f"Variable: `{var_name}`\n"
                f"Value size: {len(var_value)} characters\n"
                f"Preview: `{value_preview}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        except Exception as e:
            logger.error(f"Error processing uploaded file: {e}")
            await update.message.reply_text(f"❌ Error processing file: {str(e)}")

        # Clean up user data
        context.user_data.pop("env_var_name", None)
        return ConversationHandler.END


class CancelHandler(PrivateHandler):
    """Handler to cancel the environment variable file conversation."""

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        """Cancel the file upload conversation."""
        await update.message.reply_text(
            "⛔ *Operation cancelled* ⛔\n\n" "You can try again anytime with /set_env_file",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Clean up user data
        context.user_data.pop("env_var_name", None)
        return ConversationHandler.END


def get_read_env_file_command() -> CommandHandler:
    """Returns a command handler for reading environment variables as files."""
    return CommandHandler("read_env_file", ReadEnvFileHandler().handle)


def get_set_env_file_handler() -> ConversationHandler:
    """Returns a conversation handler for setting environment variables from files."""
    start_handler = SetEnvFileStartHandler()
    receive_handler = SetEnvFileReceiveHandler()
    cancel_handler = CancelHandler()

    return ConversationHandler(
        entry_points=[CommandHandler("set_env_file", start_handler.handle)],
        states={
            WAITING_FOR_FILE: [
                MessageHandler(filters.Document.ALL, receive_handler.handle),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler.handle)],
    )
