import json
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from telegram_bot.handlers.base.private_handler import PrivateHandler


class ListEnvHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        """List all environment variables from .env file."""
        env_file = Path(".env")

        if not env_file.exists():
            await update.message.reply_text("❌ No .env file found")
            return

        try:
            with open(env_file, "r") as f:
                lines = f.readlines()

            env_vars = []
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key = line.split("=", 1)[0]
                        env_vars.append(f"{line_num}: {key}")

            if env_vars:
                message = "🔧 Environment variables:\n\n" + "\n".join(env_vars)
            else:
                message = "📋 No environment variables found in .env file"

            await update.message.reply_text(message)

        except Exception as e:
            await update.message.reply_text(f"❌ Error reading .env file: {str(e)}")


class ReadEnvHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        """Read a specific environment variable value."""
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide a variable name: /read_env VARIABLE_NAME\n\n"
                "💡 For large values, use /read_env_file instead"
            )
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
                        if len(value) > 3500:  # Conservative limit
                            await update.message.reply_text(
                                f"⚠️ Value for `{var_name}` is too long for a message "
                                f"({len(value)} characters).\n\n"
                                f"💾 Use /read_env_file {var_name} to download as file."
                            )
                        else:
                            await update.message.reply_text(f"🔍 {var_name}={value}")
                        return

            await update.message.reply_text(f"❌ Variable '{var_name}' not found in .env file")

        except Exception as e:
            await update.message.reply_text(f"❌ Error reading .env file: {str(e)}")


class SetEnvHandler(PrivateHandler):
    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        """Set an environment variable in the .env file."""
        if len(context.args) < 2:
            await update.message.reply_text(
                "❌ Please provide variable name and value: /set_env VARIABLE_NAME value\n"
                "For complex values (JSON, etc.), enclose in quotes.\n\n"
                "💡 For large values, use /set_env_file instead"
            )
            return

        var_name = context.args[0]
        var_value = " ".join(context.args[1:])

        # Remove surrounding quotes if present
        if var_value.startswith('"') and var_value.endswith('"'):
            var_value = var_value[1:-1]
        elif var_value.startswith("'") and var_value.endswith("'"):
            var_value = var_value[1:-1]

        # Handle JSON conversion if the value looks like a complex object
        try:
            # Try to parse as JSON first to validate
            parsed_value = json.loads(var_value)
            # Convert back to single-line JSON string
            var_value = json.dumps(parsed_value)
        except (json.JSONDecodeError, TypeError):
            # Not JSON, use as-is
            pass

        env_file = Path(".env")

        try:
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

            await update.message.reply_text(f"✅ Set {var_name}={var_value}")

        except Exception as e:
            await update.message.reply_text(f"❌ Error updating .env file: {str(e)}")


def get_list_env_command() -> CommandHandler:
    return CommandHandler("list_env", ListEnvHandler().handle)


def get_read_env_command() -> CommandHandler:
    return CommandHandler("read_env", ReadEnvHandler().handle)


def get_set_env_command() -> CommandHandler:
    return CommandHandler("set_env", SetEnvHandler().handle)
