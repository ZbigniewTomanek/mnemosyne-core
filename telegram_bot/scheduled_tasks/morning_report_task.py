"""Morning Report Scheduled Task

Configures and schedules the daily morning report generation and delivery.
The morning report is sent to the configured user ID at 8:00 AM daily.
"""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import BaseModel
from telegram import Bot

from telegram_bot.constants import DEFAULT_TIMEZONE, DefaultLLMConfig
from telegram_bot.service.background_task_executor import TaskResult
from telegram_bot.service.correlation_engine.models import CorrelationFetchConfig
from telegram_bot.service.db_service import DBService
from telegram_bot.service.influxdb_garmin_data_exporter import InfluxDBGarminDataExporter
from telegram_bot.service.llm_service import LLMConfig
from telegram_bot.utils import send_message_chunks

if TYPE_CHECKING:
    from telegram_bot.service.scheduled_task_service import ScheduledTaskService


class MorningReportTaskConfig(BaseModel):
    """Configuration for the morning report scheduled task."""

    enabled: bool = True
    schedule_time: str = "0 9 * * *"  # 8:00 AM daily (cron format: minute hour day month dayofweek)
    target_user_id: int = int(os.getenv("MY_TELEGRAM_USER_ID", "0"))

    number_of_days: int = 3
    garmin_container_name: str = "garmin-fetch-data"
    calendar_lookback_days: int = 1
    calendar_lookahead_days: int = 2
    correlation_fetch: CorrelationFetchConfig = CorrelationFetchConfig()

    summarizing_llm_config: LLMConfig = DefaultLLMConfig.GEMINI_PRO


def _generate_morning_report(
    target_user_id: int,
    morning_report_config_dict: dict[str, Any],
    obsidian_config_dict: dict[str, Any],
    calendar_config_dict: dict[str, Any],
    out_dir: str,
) -> None:
    """Generate morning report - sync function that can be pickled.

    Args:
        target_user_id: The user ID to generate report for
        morning_report_config_dict: Serialized config dict for MorningReportConfig
        obsidian_config_dict: Serialized config dict for ObsidianConfig
        calendar_config_dict: Serialized config dict for CalendarConfig
        out_dir: Base output directory for bot persistence (SQLite, logs)

    Returns:
        Generated morning report text
    """
    import asyncio

    from telegram_bot.service.calendar_service.calendar_service import CalendarConfig, CalendarService
    from telegram_bot.service.morning_report_service import MorningReportConfig, MorningReportService
    from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig, ObsidianService

    morning_report_config = MorningReportConfig(**morning_report_config_dict)
    obsidian_config = ObsidianConfig(**obsidian_config_dict)
    calendar_config = CalendarConfig(**calendar_config_dict)

    obsidian_service = ObsidianService(obsidian_config)
    calendar_service = CalendarService(calendar_config)
    db_service = DBService(Path(out_dir))

    morning_report_service = MorningReportService(
        morning_report_config,
        obsidian_service,
        db_service=db_service,
        tz=ZoneInfo(DEFAULT_TIMEZONE),
        garmin_data_exporter=InfluxDBGarminDataExporter(),
        calendar_service=calendar_service,
    )

    # Generate the morning report
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        report = loop.run_until_complete(morning_report_service.create_morning_summary(user_id=target_user_id))
        return report
    finally:
        loop.close()


async def _morning_report_callback(
    task_result: TaskResult[str],
    target_user_id: int,
    bot_token: str,
) -> None:
    """Callback to send the generated morning report via Telegram.

    Args:
        task_result: Result from the morning report generation task
        target_user_id: User ID to send report to
        bot_token: Bot token for sending messages
    """
    from telegram import Bot
    from telegram.error import TelegramError

    bot = Bot(token=bot_token)

    if task_result.exception:
        logger.error("Failed to generate morning report: {}", task_result.exception)
        try:
            await bot.send_message(
                chat_id=target_user_id, text=f"❌ Failed to generate morning report: {task_result.exception}"
            )
        except TelegramError as e:
            logger.error("Failed to send error message via Telegram: {}", e)
        return

    if not task_result.result:
        logger.error("Morning report generation returned empty result")
        return

    # Send the morning report using chunked message function
    await send_message_chunks(bot, target_user_id, task_result.result)
    logger.success("Morning report sent successfully to user {}", target_user_id)


class MorningReportTask:
    """Scheduled task that generates and sends daily morning reports."""

    def __init__(
        self,
        config: MorningReportTaskConfig,
        obsidian_config,
        calendar_config,
        bot: Bot,
        out_dir: Path,
    ):
        self.config = config
        self.obsidian_config = obsidian_config
        self.calendar_config = calendar_config
        self.bot = bot
        self._out_dir = out_dir
        self._morning_report_config_dict = self._serialize_morning_report_config()
        self._obsidian_config_dict = self._serialize_obsidian_config()
        self._calendar_config_dict = self._serialize_calendar_config()

    def _serialize_morning_report_config(self) -> dict[str, Any]:
        """Serialize the morning report config to a pickleable dict."""
        return {
            "summarizing_llm_config": self.config.summarizing_llm_config.model_dump(),
            "number_of_days": self.config.number_of_days,
            "garmin_container_name": self.config.garmin_container_name,
            "calendar_lookback_days": self.config.calendar_lookback_days,
            "calendar_lookahead_days": self.config.calendar_lookahead_days,
            "correlation_lookback_days": self.config.correlation_fetch.lookback_days,
            "correlation_max_events": self.config.correlation_fetch.max_events,
        }

    def _serialize_obsidian_config(self) -> dict[str, Any]:
        """Serialize the obsidian config to a pickleable dict."""
        return {
            "obsidian_root_dir": str(self.obsidian_config.obsidian_root_dir),
            "daily_notes_dir": str(self.obsidian_config.daily_notes_dir),
            "ai_assistant_memory_logs": str(self.obsidian_config.ai_assistant_memory_logs),
        }

    def _serialize_calendar_config(self) -> dict[str, Any]:
        """Serialize the calendar config to a pickleable dict."""
        return {
            "backend": self.calendar_config.backend,
            "default_lookback_days": self.calendar_config.default_lookback_days,
            "default_lookahead_days": self.calendar_config.default_lookahead_days,
            "timezone": self.calendar_config.timezone,
        }

    def register_with_scheduler(self, scheduler: ScheduledTaskService) -> None:
        """Register the morning report task with the scheduler."""
        if not self.config.enabled:
            logger.info("Morning report task is disabled, not registering with scheduler")
            return

        logger.info("Registering morning report task with schedule: {}", self.config.schedule_time)

        # Create a partial callback function with the required parameters

        callback_fn = partial(
            _morning_report_callback,
            target_user_id=self.config.target_user_id,
            bot_token=self.bot.token,
        )

        scheduler.add_job_to_background_executor(
            cron_expression=self.config.schedule_time,
            target_fn=_generate_morning_report,
            target_args=(
                self.config.target_user_id,
                self._morning_report_config_dict,
                self._obsidian_config_dict,
                self._calendar_config_dict,
                str(self._out_dir),
            ),
            callback_fn=callback_fn,
            job_id="morning_report",
            display_name="Morning Report",
            description="Generates and sends the daily morning report via Telegram.",
            metadata={"target_user_id": self.config.target_user_id},
        )

        logger.info("Morning report task registered successfully")


def create_morning_report_task(
    config: MorningReportTaskConfig, obsidian_config, calendar_config, bot: Bot, out_dir: Path
) -> MorningReportTask:
    """Factory function to create a configured morning report task."""
    return MorningReportTask(config, obsidian_config, calendar_config, bot, out_dir)
