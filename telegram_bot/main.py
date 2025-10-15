from __future__ import annotations

import asyncio
import atexit
from pathlib import Path

from loguru import logger
from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    Update,
)
from telegram.ext import Application, ApplicationBuilder

from telegram_bot.config import BotSettings
from telegram_bot.handlers.commands.env_commands import get_list_env_command, get_read_env_command, get_set_env_command
from telegram_bot.handlers.commands.garmin_commands import get_garmin_disconnect_command, get_garmin_status_command
from telegram_bot.handlers.commands.list_drug_command import get_list_drugs_command
from telegram_bot.handlers.commands.list_food_command import get_list_food_command
from telegram_bot.handlers.commands.logs_command import get_logs_command
from telegram_bot.handlers.commands.semantic_search_command import get_search_obsidian_command
from telegram_bot.handlers.commands.technical_commands import get_restart_command
from telegram_bot.handlers.conversations.env_file_conversation import (
    get_read_env_file_command,
    get_set_env_file_handler,
)
from telegram_bot.handlers.conversations.garmin_auth_conversation import get_garmin_auth_handler
from telegram_bot.handlers.conversations.garmin_export_conversation import get_garmin_export_handler
from telegram_bot.handlers.conversations.life_context_export_conversation import get_life_context_export_handler
from telegram_bot.handlers.conversations.log_drug_conversation import get_drug_log_handler
from telegram_bot.handlers.conversations.log_food_conversation import get_food_log_handler
from telegram_bot.handlers.conversations.scheduled_jobs_conversation import get_scheduled_jobs_handler
from telegram_bot.handlers.messages import get_default_message_handler, get_voice_message_handler
from telegram_bot.scheduled_tasks.correlation_engine_task import CorrelationEngineTask
from telegram_bot.scheduled_tasks.memory_consolidation_task import MemoryConsolidationTask
from telegram_bot.scheduled_tasks.morning_report_task import MorningReportTask
from telegram_bot.scheduled_tasks.obsidian_embedding_task import register_obsidian_embedding_refresh_task
from telegram_bot.scheduled_tasks.smart_context_trigger_task import SmartContextTriggerTask
from telegram_bot.service.context_trigger import ContextAnalyzerService, ContextTriggerExecutor
from telegram_bot.service.llm_service import LLMService
from telegram_bot.service_factory import ServiceFactory

BOT_SETTINGS = BotSettings()
SERVICE_FACTORY = ServiceFactory(BOT_SETTINGS)


def setup_logger(out_dir: Path) -> None:
    log_dir = out_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(log_dir / "debug.log", rotation="100 MB", retention="7 days", level="DEBUG")
    logger.add(log_dir / "error.log", rotation="100 MB", retention="7 days", level="ERROR")
    logger.info("logger initialised")


def _build_commands() -> dict[str, list[BotCommand]]:
    common = [
        BotCommand("log_food", "Log your food consumption"),
        BotCommand("list_food", "View your food logs"),
        BotCommand("log_drug", "Log drug usage"),
        BotCommand("list_drugs", "View your drug logs"),
        BotCommand("search_obsidian", "Search Obsidian notes semantically"),
        BotCommand("export_context", "Export life context summary"),
        BotCommand("cancel", "Cancel current conversation"),
    ]

    garmin = [
        BotCommand("connect_garmin", "Connect your Garmin account"),
        BotCommand("garmin_export", "Export data from Garmin Connect"),
        BotCommand("garmin_status", "Check Garmin Connect status"),
        BotCommand("disconnect_garmin", "Disconnect your Garmin account"),
    ]

    technical = [
        BotCommand("restart", "Restart the bot"),
        BotCommand("get_logs", "Get last N log entries with AI analysis"),
        BotCommand("list_env", "List all environment variables"),
        BotCommand("read_env", "Read a specific environment variable"),
        BotCommand("set_env", "Set an environment variable"),
        BotCommand("read_env_file", "Read env variable as downloadable file"),
        BotCommand("set_env_file", "Set env variable from uploaded file"),
        BotCommand("scheduled_jobs", "List scheduled jobs and run one now"),
    ]

    return {
        "default": common + garmin + technical,
        "private": common + garmin + technical,
        "group": common,
    }


async def _post_init(application: Application) -> None:
    commands = _build_commands()

    await SERVICE_FACTORY.background_task_executor.start_workers()
    await register_scheduled_tasks(application)
    await SERVICE_FACTORY.scheduled_task_service.start()

    async def stop_all_services() -> None:
        # Send shutdown message to the configured user
        try:
            await application.bot.send_message(  # noqa: F821
                chat_id=BOT_SETTINGS.my_telegram_user_id, text="🤖 Bot is shutting down. All systems stopping."
            )
            logger.info(f"Shutdown message sent to user {BOT_SETTINGS.my_telegram_user_id}")
        except Exception as e:
            logger.error(f"Failed to send shutdown message: {e}")

        await SERVICE_FACTORY.scheduled_task_service.stop()
        await SERVICE_FACTORY.background_task_executor.stop_workers(False)

    def shutdown_services():
        """Synchronous wrapper for async shutdown."""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(stop_all_services())
        else:
            asyncio.run(stop_all_services())

    atexit.register(shutdown_services)

    matrix: list[tuple[list[BotCommand], object, str | None]] = [
        (commands["private"], BotCommandScopeAllPrivateChats(), None),
        (commands["group"], BotCommandScopeAllGroupChats(), None),
        (commands["default"], BotCommandScopeDefault(), None),
        (commands["default"], BotCommandScopeDefault(), "en"),
    ]

    await asyncio.gather(
        *(
            application.bot.set_my_commands(cmds, scope=scope, language_code=lang)  # noqa: F821
            for cmds, scope, lang in matrix
        )
    )
    logger.info("Bot commands registered.")

    # Send startup message to the configured user
    try:
        await application.bot.send_message(  # noqa: F821
            chat_id=BOT_SETTINGS.my_telegram_user_id, text="🤖 Bot is up and functional! All systems ready."
        )
        logger.info(f"Startup message sent to user {BOT_SETTINGS.my_telegram_user_id}")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")


async def register_scheduled_tasks(application: Application) -> None:
    """Register scheduled tasks with the ScheduledTaskService."""
    scheduler = SERVICE_FACTORY.scheduled_task_service

    # Create and register the morning report task
    morning_report_task = MorningReportTask(
        BOT_SETTINGS.morning_report,
        BOT_SETTINGS.obsidian_config,
        BOT_SETTINGS.calendar_config,
        application.bot,  # noqa: F821
        BOT_SETTINGS.out_dir,
    )
    morning_report_task.register_with_scheduler(scheduler)

    # Create and register the memory consolidation task
    memory_consolidation_task = MemoryConsolidationTask(
        BOT_SETTINGS.memory_consolidation, BOT_SETTINGS.obsidian_config, application.bot  # noqa: F821
    )
    memory_consolidation_task.register_with_scheduler(scheduler)

    # Register correlation engine task
    correlation_task = CorrelationEngineTask(
        BOT_SETTINGS.correlation_engine,
        SERVICE_FACTORY.correlation_job_runner,
        application.bot,  # noqa: F821
        BOT_SETTINGS.my_telegram_user_id,
    )
    correlation_task.register_with_scheduler(scheduler)

    register_obsidian_embedding_refresh_task(
        scheduler,
        SERVICE_FACTORY,
        BOT_SETTINGS.chroma_vector_store,
    )

    # Register Smart Context Triggers
    await register_smart_context_triggers(scheduler, application)

    logger.info("Scheduled tasks registered successfully.")


async def register_smart_context_triggers(scheduler, application: Application) -> None:
    """Register all configured smart context triggers as scheduled tasks."""
    trigger_configs = BOT_SETTINGS.context_trigger_task_config

    if not trigger_configs:
        logger.info("No Smart Context Triggers configured")
        return

    logger.info(f"Setting up {len(trigger_configs)} Smart Context Triggers")

    existing_ids: set[str] = set()

    for cron_schedule, trigger_config in trigger_configs.items():
        analyzer = ContextAnalyzerService(LLMService(trigger_config.llm_config))
        executor = ContextTriggerExecutor(
            config=trigger_config,
            aggregator=SERVICE_FACTORY.context_aggregator,
            analyzer=analyzer,
            obsidian_service=SERVICE_FACTORY.obsidian_service,
            telegram_bot=application.bot,  # noqa: F821
            user_id=BOT_SETTINGS.my_telegram_user_id,
            tz=BOT_SETTINGS.tz,
        )

        # Create and register the task wrapper
        trigger_task = SmartContextTriggerTask(executor)

        # Register with existing scheduler infrastructure
        base_job_id = "context_trigger_" + "".join(
            ch.lower() if ch.isalnum() else "_" for ch in trigger_config.name
        ).strip("_")
        job_id = base_job_id
        counter = 1
        while job_id in existing_ids:
            counter += 1
            job_id = f"{base_job_id}_{counter}"
        existing_ids.add(job_id)

        scheduler.add_job_to_background_executor(
            cron_expression=cron_schedule,
            target_fn=trigger_task.run,
            target_args=(),
            target_kwargs={},
            job_id=job_id,
            display_name=trigger_config.name,
            description=trigger_config.description,
            metadata={"cron": cron_schedule},
        )
        logger.info(f"✅ Registered trigger '{trigger_config.name}' with schedule '{cron_schedule}'")


def _build_app(bot_settings: BotSettings) -> Application:
    application = (
        ApplicationBuilder()
        .token(bot_settings.telegram_bot_api_key)
        .concurrent_updates(True)
        .read_timeout(bot_settings.read_timeout_s)
        .write_timeout(bot_settings.write_timeout_s)
        .post_init(_post_init)
        .build()
    )
    return application


def _setup_handlers(app: Application) -> None:
    app.add_handler(get_food_log_handler(SERVICE_FACTORY.db_service))
    app.add_handler(get_drug_log_handler(SERVICE_FACTORY.db_service))
    app.add_handler(get_list_food_command(SERVICE_FACTORY.db_service))
    app.add_handler(get_list_drugs_command(SERVICE_FACTORY.db_service))

    app.add_handler(get_garmin_auth_handler(SERVICE_FACTORY.garmin_connect_service))
    app.add_handler(get_garmin_export_handler(SERVICE_FACTORY.garmin_connect_service))
    app.add_handler(get_garmin_status_command(SERVICE_FACTORY.garmin_connect_service))
    app.add_handler(get_garmin_disconnect_command(SERVICE_FACTORY.garmin_connect_service))
    app.add_handler(get_life_context_export_handler(SERVICE_FACTORY.life_context_service, BOT_SETTINGS.tz))
    app.add_handler(
        get_search_obsidian_command(
            SERVICE_FACTORY.obsidian_embedding_indexer, BOT_SETTINGS.obsidian_config.obsidian_root_dir.name
        )
    )
    app.add_handler(get_restart_command())
    app.add_handler(get_logs_command(BOT_SETTINGS.log_analysis))
    app.add_handler(get_list_env_command())
    app.add_handler(get_read_env_command())
    app.add_handler(get_set_env_command())
    app.add_handler(get_read_env_file_command())
    app.add_handler(get_set_env_file_handler())
    app.add_handler(get_scheduled_jobs_handler(SERVICE_FACTORY.scheduled_jobs_facade))

    app.add_handler(
        get_voice_message_handler(
            message_transcription_service=SERVICE_FACTORY.message_transcription_service,
            ai_assistant_service=SERVICE_FACTORY.ai_assistant_service,
        )
    )
    app.add_handler(get_default_message_handler(SERVICE_FACTORY.ai_assistant_service))


def build_configured_application() -> Application:
    if not BOT_SETTINGS.out_dir.exists():
        BOT_SETTINGS.out_dir.mkdir(parents=True)
    setup_logger(BOT_SETTINGS.out_dir)
    application = _build_app(BOT_SETTINGS)

    _setup_handlers(application)
    return application


def main() -> None:  # pragma: no cover
    application = build_configured_application()
    logger.info("Starting polling …")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
