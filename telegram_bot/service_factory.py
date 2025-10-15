from functools import cached_property

from telegram_bot.config import BotSettings
from telegram_bot.service.ai_assitant_service import AIAssistantService
from telegram_bot.service.background_task_executor import BackgroundTaskExecutor
from telegram_bot.service.calendar_service.calendar_service import CalendarService
from telegram_bot.service.context_trigger import ContextAggregator
from telegram_bot.service.correlation_engine.engine import CorrelationEngine
from telegram_bot.service.correlation_engine.job import CorrelationJobRunner
from telegram_bot.service.correlation_engine.sleep import SleepAnalysisService
from telegram_bot.service.correlation_engine.sources import (
    CalendarEventSource,
    GarminActivityEventSource,
    GarminExportDataCache,
    InfluxMetricSource,
)
from telegram_bot.service.correlation_engine.stats import WelchTTest
from telegram_bot.service.correlation_engine.variance import ActivityImpactVarianceService
from telegram_bot.service.db_service import DBService
from telegram_bot.service.garmin_connect_service import GarminConnectService
from telegram_bot.service.garmin_data_analysis_service import GarminDataAnalysisService
from telegram_bot.service.influxdb_garmin_data_exporter import InfluxDBGarminDataExporter
from telegram_bot.service.life_context import LifeContextService
from telegram_bot.service.life_context.garmin import GarminContextService
from telegram_bot.service.message_transcription_service import MessageTranscriptionService
from telegram_bot.service.obsidian.obsidian_daily_notes_manager import ObsidianDailyNotesManager
from telegram_bot.service.obsidian.obsidian_embedding_service import ObsidianEmbeddingIndexer
from telegram_bot.service.obsidian.obsidian_service import ObsidianService
from telegram_bot.service.scheduled_jobs_facade import ScheduledJobsFacade
from telegram_bot.service.scheduled_task_service import ScheduledTaskService
from telegram_bot.service.vector_store.chroma_vector_store import ChromaVectorStore
from telegram_bot.service.vector_store.sentence_transformer_embedding import SentenceTransformerEmbeddingFunction


class ServiceFactory:
    def __init__(self, bot_settings: BotSettings):
        self.bot_settings = bot_settings

    @cached_property
    def db_service(self) -> DBService:
        return DBService(self.bot_settings.out_dir)

    @cached_property
    def garmin_connect_service(self) -> GarminConnectService:
        return GarminConnectService(
            self.bot_settings.garmin_token_dir,
        )

    @cached_property
    def background_task_executor(self) -> BackgroundTaskExecutor:
        return BackgroundTaskExecutor(
            num_async_workers=self.bot_settings.executor_num_async_workers,
            num_cpu_workers=self.bot_settings.executor_num_cpu_workers,
        )

    @cached_property
    def message_transcription_service(self) -> MessageTranscriptionService:
        return MessageTranscriptionService(
            background_task_executor=self.background_task_executor, whisper_settings=self.bot_settings.whisper
        )

    @cached_property
    def ai_assistant_service(self) -> AIAssistantService:
        return AIAssistantService(
            db_service=self.db_service,
            bot_settings=self.bot_settings,
            obsidian_daily_notes_manager=self.obsidian_daily_notes_manager,
            life_context_service=self.life_context_service,
            obsidian_embedding_indexer=self.obsidian_embedding_indexer,
        )

    @cached_property
    def garmin_data_analysis_service(self) -> GarminDataAnalysisService:
        return GarminDataAnalysisService(garmin_service=self.garmin_connect_service, out_dir=self.bot_settings.out_dir)

    @cached_property
    def scheduled_task_service(self) -> ScheduledTaskService:
        return ScheduledTaskService(background_task_executor=self.background_task_executor)

    @cached_property
    def scheduled_jobs_facade(self) -> ScheduledJobsFacade:
        return ScheduledJobsFacade(self.scheduled_task_service)

    @cached_property
    def embedding_function(self) -> SentenceTransformerEmbeddingFunction:
        model_name = self.bot_settings.chroma_vector_store.embedding_model_name
        return SentenceTransformerEmbeddingFunction(model_name=model_name)

    @cached_property
    def chroma_vector_store(self) -> ChromaVectorStore:
        return ChromaVectorStore(
            config=self.bot_settings.chroma_vector_store,
            embedding_function=self.embedding_function,
            out_dir=self.bot_settings.out_dir,
        )

    @cached_property
    def obsidian_embedding_indexer(self) -> ObsidianEmbeddingIndexer:
        return ObsidianEmbeddingIndexer(
            obsidian_service=self.obsidian_service,
            vector_store=self.chroma_vector_store,
            config=self.bot_settings.chroma_vector_store,
            out_dir=self.bot_settings.out_dir,
        )

    @cached_property
    def obsidian_service(self) -> ObsidianService:
        return ObsidianService(
            self.bot_settings.obsidian_config,
        )

    @cached_property
    def obsidian_daily_notes_manager(self) -> ObsidianDailyNotesManager:
        return ObsidianDailyNotesManager(
            obsidian_service=self.obsidian_service,
            manager_config=self.bot_settings.obsidian_daily_notes_manager_config,
        )

    @cached_property
    def influxdb_garmin_data_exporter(self):
        return InfluxDBGarminDataExporter()

    @cached_property
    def calendar_service(self) -> CalendarService:
        return CalendarService(self.bot_settings.calendar_config)

    @cached_property
    def context_aggregator(self) -> ContextAggregator:
        return ContextAggregator(
            life_context_service=self.life_context_service,
            tz=self.bot_settings.tz,
        )

    @cached_property
    def garmin_context_service(self) -> GarminContextService:
        return GarminContextService(self.influxdb_garmin_data_exporter)

    @cached_property
    def life_context_service(self) -> LifeContextService:
        return LifeContextService(
            config=self.bot_settings.life_context,
            tz=self.bot_settings.tz,
            obsidian_service=self.obsidian_service,
            garmin_service=self.garmin_context_service,
            calendar_service=self.calendar_service,
            db_service=self.db_service,
        )

    @cached_property
    def correlation_metric_source(self) -> InfluxMetricSource:
        return InfluxMetricSource(
            cache=self.garmin_export_cache,
            tz=self.bot_settings.tz,
        )

    @cached_property
    def correlation_event_source(self) -> CalendarEventSource:
        return CalendarEventSource(
            calendar_service=self.calendar_service,
            tz=self.bot_settings.tz,
        )

    @cached_property
    def garmin_export_cache(self) -> GarminExportDataCache:
        return GarminExportDataCache(
            self.influxdb_garmin_data_exporter,
            cache_timeout_hours=self.bot_settings.correlation_engine.sources.cache_timeout_hours,
        )

    @cached_property
    def garmin_activity_event_source(self) -> GarminActivityEventSource:
        return GarminActivityEventSource(
            cache=self.garmin_export_cache,
            tz=self.bot_settings.tz,
        )

    @cached_property
    def sleep_analysis_service(self) -> SleepAnalysisService:
        return SleepAnalysisService(
            cache=self.garmin_export_cache,
            tz=self.bot_settings.tz,
        )

    @cached_property
    def activity_variance_service(self) -> ActivityImpactVarianceService:
        return ActivityImpactVarianceService(db_service=self.db_service)

    @cached_property
    def correlation_engine(self) -> CorrelationEngine:
        return CorrelationEngine(
            metric_source=self.correlation_metric_source,
            db_service=self.db_service,
            stats_calculator=WelchTTest(),
            sleep_service=self.sleep_analysis_service,
            variance_service=self.activity_variance_service,
        )

    @cached_property
    def correlation_job_runner(self) -> CorrelationJobRunner:
        return CorrelationJobRunner(
            engine=self.correlation_engine,
            event_sources=[self.correlation_event_source, self.garmin_activity_event_source],
            config=self.bot_settings.correlation_engine,
            user_id=self.bot_settings.my_telegram_user_id,
        )
