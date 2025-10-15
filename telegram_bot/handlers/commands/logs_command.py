import tempfile
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from telegram_bot.handlers.base.private_handler import PrivateHandler
from telegram_bot.service.llm_service import LLMConfig, LLMService


class LogAnalysisConfig(BaseModel):
    llm_config: LLMConfig = LLMConfig(
        llm_class_path="langchain_openai.ChatOpenAI", llm_kwargs={"model_name": "gpt-4o-mini", "temperature": 0.3}
    )
    log_analysis_prompt: str = """
Please analyze the following log entries and provide a brief summary of:
1. What the system was doing
2. Any errors or warnings
3. Overall system status

Log entries:
{log_content}
"""


class GetLogsHandler(PrivateHandler):
    def __init__(self, log_analysis_config: LogAnalysisConfig) -> None:
        super().__init__()
        self.log_analysis_config = log_analysis_config
        self.llm_service = LLMService(log_analysis_config.llm_config)

    async def _handle(self, update: Update, context: CallbackContext) -> Any:
        """
        Handle the /get_logs command.

        Args:
            update: The update containing the message.
            context: The callback context.
        """
        # Parse number of lines from command arguments, default to 15
        lines = 15
        if context.args and len(context.args) > 0:
            try:
                lines = int(context.args[0])
                if lines <= 0:
                    await update.message.reply_text("Number of lines must be positive!")
                    return
            except ValueError:
                await update.message.reply_text("Invalid number format! Using default 15 lines.")
                lines = 15

        try:
            # Find the debug log file
            log_file_path = Path("out/log/debug.log")
            if not log_file_path.exists():
                await update.message.reply_text("❌ Log file not found!")
                return

            # Read last N lines from the log file
            with open(log_file_path, "r", encoding="utf-8") as f:
                log_lines = f.readlines()
                last_lines = log_lines[-lines:]
                log_content = "".join(last_lines)

            # Create temporary file with the logs
            with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as temp_file:
                temp_file.write(log_content)
                temp_file_path = temp_file.name

            # Send the log file
            with open(temp_file_path, "rb") as log_file:
                await update.message.reply_document(
                    document=log_file, filename=f"last_{lines}_logs.log", caption=f"📋 Last {lines} log entries"
                )

            # Clean up temporary file
            Path(temp_file_path).unlink()

            # Generate LLM analysis of the logs
            analysis_prompt = self.log_analysis_config.log_analysis_prompt.format(log_content=log_content)

            if len(analysis_prompt) >= 64_000:
                await update.message.reply_text(
                    "⚠️ Log content too large for analysis. Please reduce the number of lines."
                )
                return

            try:
                analysis = await self.llm_service.aprompt_llm(analysis_prompt)
                await update.message.reply_text(f"🤖 **Log Analysis:**\n\n{analysis}")
            except Exception as e:
                logger.error(f"Failed to analyze logs with LLM: {e}")
                await update.message.reply_text("⚠️ Log file sent, but analysis failed.")

        except Exception as e:
            logger.error(f"Error in get_logs command: {e}")
            await update.message.reply_text(f"❌ Error retrieving logs: {e}")


def get_logs_command(log_analysis_config: LogAnalysisConfig) -> CommandHandler:
    return CommandHandler("get_logs", GetLogsHandler(log_analysis_config).handle)
