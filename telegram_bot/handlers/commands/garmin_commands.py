#!/usr/bin/env python3
"""
Command handlers for Garmin Connect integration.

This module provides command handlers for Garmin Connect operations like
checking status and disconnecting accounts.
"""

import shutil

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler

from telegram_bot.handlers.base.public_handler import PublicHandler
from telegram_bot.service.garmin_connect_service import GarminConnectService


class GarminStatusHandler(PublicHandler):
    """
    Handler for the /garmin_status command.

    Checks if the user has a connected Garmin Connect account.
    """

    def __init__(self, garmin_service: GarminConnectService) -> None:
        """
        Initialize the handler with a GarminConnectService.

        Args:
            garmin_service: The GarminConnectService to use.
        """
        super().__init__()
        self.garmin_service = garmin_service

    async def _handle(self, update: Update, context: CallbackContext) -> None:
        """
        Handle the /garmin_status command.

        Args:
            update: The update containing the message.
            context: The callback context.
        """
        user_id = update.effective_user.id
        is_connected = self.garmin_service.account_manager.is_authenticated(user_id)

        if is_connected:
            await update.message.reply_text(
                "✅ *Your Garmin Connect account is linked* ✅\n\n"
                "🏃‍♂️ Use /garmin\\_export to export your health and fitness data 📊",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "❌ *No Garmin Connect account is linked* ❌\n\n" "🔗 Use /connect\\_garmin to link your account 🔗",
                parse_mode=ParseMode.MARKDOWN,
            )


class GarminDisconnectHandler(PublicHandler):
    """
    Handler for the /disconnect_garmin command.

    Disconnects a user's Garmin Connect account by removing the stored tokens.
    """

    def __init__(self, garmin_service: GarminConnectService) -> None:
        """
        Initialize the handler with a GarminConnectService.

        Args:
            garmin_service: The GarminConnectService to use.
        """
        super().__init__()
        self.garmin_service = garmin_service

    async def _handle(self, update: Update, context: CallbackContext) -> None:
        """
        Handle the /disconnect_garmin command.

        Args:
            update: The update containing the message.
            context: The callback context.
        """
        user_id = update.effective_user.id

        # Check if user is authenticated
        if not self.garmin_service.account_manager.is_authenticated(user_id):
            await update.message.reply_text(
                "❌ *No Garmin Connect account is currently linked* ❌", parse_mode=ParseMode.MARKDOWN
            )
            return

        # Delete the token directory
        token_dir = self.garmin_service.account_manager.get_user_token_path(user_id)
        logger.info(f"Deleting Garmin Connect tokens for user {user_id} from {token_dir}")
        shutil.rmtree(token_dir, ignore_errors=True)

        await update.message.reply_text(
            "✅ *Your Garmin Connect account has been disconnected* ✅\n\n"
            "🔐 Your tokens have been deleted.\n"
            "🔄 Use /connect\\_garmin to link again.",
            parse_mode=ParseMode.MARKDOWN,
        )


def get_garmin_status_command(garmin_service: GarminConnectService) -> CommandHandler:
    """
    Returns a command handler for checking Garmin connection status.

    Args:
        garmin_service: The GarminConnectService to use.

    Returns:
        A CommandHandler for the /garmin_status command.
    """
    handler = GarminStatusHandler(garmin_service)
    return CommandHandler("garmin_status", handler.handle)


def get_garmin_disconnect_command(garmin_service: GarminConnectService) -> CommandHandler:
    """
    Returns a command handler for disconnecting Garmin account.

    Args:
        garmin_service: The GarminConnectService to use.

    Returns:
        A CommandHandler for the /disconnect_garmin command.
    """
    handler = GarminDisconnectHandler(garmin_service)
    return CommandHandler("disconnect_garmin", handler.handle)
