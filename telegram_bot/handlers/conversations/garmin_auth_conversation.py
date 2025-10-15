#!/usr/bin/env python3
"""
Garmin Connect authentication conversation handler for the Telegram bot.

This module provides the conversation handler for authenticating a user with Garmin Connect.
"""

from typing import Any

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler, ConversationHandler, MessageHandler, filters

from telegram_bot.handlers.base.public_handler import PublicHandler
from telegram_bot.service.garmin_connect_service import GarminConnectService

# Conversation states
EMAIL, PASSWORD, MFA = range(3)

# In-memory storage for MFA states
mfa_states: dict[int, Any] = {}


class GarminAuthHandler(PublicHandler):
    """
    Handler for the Garmin Connect authentication conversation.
    """

    def __init__(self, garmin_service: GarminConnectService) -> None:
        """
        Initialize the handler with a GarminConnectService.

        Args:
            garmin_service: The GarminConnectService to use for authentication.
        """
        super().__init__()
        self.garmin_service = garmin_service

    async def start_auth(self, update: Update, context: CallbackContext) -> int:
        """
        Start the authentication conversation.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        await update.message.reply_text(
            "🏃‍♂️ *GARMIN CONNECT AUTHORIZATION* 🏃‍♂️\n\n"
            "Let's connect your Garmin account to access your health and fitness data.\n\n"
            "📧 Please enter your *Garmin Connect email address*:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return EMAIL

    async def receive_email(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the email input from the user.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        user_id = update.effective_user.id
        email = update.message.text
        context.user_data["garmin_email"] = email

        logger.info(f"Received Garmin Connect email for user {user_id}")

        await update.message.reply_text(
            "🔐 *PASSWORD REQUIRED* 🔐\n\n"
            "Thank you! Now, please enter your Garmin Connect password.\n\n"
            "⚠️ _Note: Your password is used only for authentication and is never stored._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return PASSWORD

    async def receive_password(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the password input from the user.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        user_id = update.effective_user.id
        email = context.user_data["garmin_email"]
        password = update.message.text

        # Delete the message containing the password for security
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete password message: {e}")

        await update.message.reply_text("🕐 *Authenticating with Garmin Connect...* 🕐", parse_mode=ParseMode.MARKDOWN)
        result, data = await self.garmin_service.authenticate_user(user_id, email, password)

        if result == "needs_mfa":
            # Store login state for MFA completion
            mfa_states[user_id] = data
            await update.message.reply_text(
                "📲 *MULTI-FACTOR AUTHENTICATION REQUIRED* 📲\n\n"
                "Garmin Connect requires additional verification.\n\n"
                "🔢 Please enter the code from your authenticator app:",
                parse_mode=ParseMode.MARKDOWN,
            )
            return MFA
        elif result:
            await update.message.reply_text(
                "✅ *Authentication successful!* ✅\n\n"
                "Your Garmin Connect account is now linked.\n\n"
                "📈 Use /garmin\\_export to access your fitness data.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                f"❌ *Authentication failed* ❌\n\n"
                f"_Error: {data}_\n\n"
                "Please try again with /connect\\_garmin or contact support if the issue persists.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END

    async def receive_mfa(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the MFA code input from the user.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        user_id = update.effective_user.id
        mfa_code = update.message.text
        login_state = mfa_states.get(user_id)

        if not login_state:
            await update.message.reply_text(
                "⏰ *MFA session expired* ⏰\n\nPlease start again with /connect\\_garmin",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END

        await update.message.reply_text("🔒 *Verifying MFA code...* 🔒", parse_mode=ParseMode.MARKDOWN)
        success = await self.garmin_service.handle_mfa(user_id, mfa_code, login_state)

        if success:
            await update.message.reply_text(
                "✅ *Authentication successful!* ✅\n\n"
                "Your Garmin Connect account is now linked.\n\n"
                "📈 Use /garmin\\_export to access your fitness data.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "❌ *MFA verification failed* ❌\n\nPlease try again with /connect\\_garmin",
                parse_mode=ParseMode.MARKDOWN,
            )

        # Clean up the MFA state
        if user_id in mfa_states:
            del mfa_states[user_id]

        return ConversationHandler.END

    async def cancel(self, update: Update, context: CallbackContext) -> int:
        """
        Cancel the authentication conversation.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The end of conversation.
        """
        await update.message.reply_text(
            "⛔ *Authentication cancelled* ⛔\n\nYou can try again anytime with /connect\\_garmin",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    async def _handle(self, update: Update, context: CallbackContext) -> int:
        """
        Handle the command that starts the authentication conversation.

        This is the entry point for the conversation when used as a standalone handler.

        Args:
            update: The update containing the message.
            context: The callback context.

        Returns:
            The next conversation state.
        """
        return await self.start_auth(update, context)


def get_garmin_auth_handler(garmin_service: GarminConnectService) -> ConversationHandler:
    """
    Returns a conversation handler for Garmin Connect authentication.

    Args:
        garmin_service: The GarminConnectService to use for authentication.

    Returns:
        A ConversationHandler configured for the authentication flow.
    """
    handler = GarminAuthHandler(garmin_service)

    return ConversationHandler(
        entry_points=[CommandHandler("connect_garmin", handler.handle)],
        states={
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_email)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_password)],
            MFA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handler.receive_mfa)],
        },
        fallbacks=[CommandHandler("cancel", handler.cancel)],
    )
