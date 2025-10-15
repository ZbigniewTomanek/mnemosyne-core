from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger
from pydantic import BaseModel

from telegram_bot.service.calendar_service.calendar_service import CalendarService
from telegram_bot.service.calendar_service.models import CalendarEventQuery
from telegram_bot.service.context_trigger.garmin_formatter import (
    format_current_sleep_status_md,
    format_garmin_day_markdown_md,
)
from telegram_bot.service.correlation_engine.formatting import format_correlation_events
from telegram_bot.service.correlation_engine.models import CorrelationFetchConfig
from telegram_bot.service.db_service import DBService
from telegram_bot.service.influxdb_garmin_data_exporter import GarminExportData, InfluxDBGarminDataExporter
from telegram_bot.service.llm_service import LLMConfig, LLMService
from telegram_bot.service.obsidian.obsidian_service import ObsidianService
from telegram_bot.utils import clean_ai_response


class Activity(BaseModel):
    name: str
    calories: int
    duration_min: int
    avg_hr: Optional[int]
    start_time: str
    distance_km: Optional[float]


class StressSummary(BaseModel):
    stress_pct: float
    low_pct: float
    medium_pct: float
    high_pct: float


class BodyBatterySummary(BaseModel):
    high: int
    low: int
    avg: int


class DailyMetrics(BaseModel):
    date: date
    steps: int
    active_kcal: int
    resting_hr: int
    hr_min: int
    hr_max: int
    hr_avg: int
    stress: StressSummary
    body_battery: BodyBatterySummary
    activities: list[Activity] = []


class MorningReportConfig(BaseModel):
    summarizing_llm_config: LLMConfig
    number_of_days: int = 5  # look-back horizon (24 h increments)
    garmin_container_name: str = "garmin-fetch-data"
    calendar_lookback_days: int = 1
    calendar_lookahead_days: int = 2
    correlation_fetch: CorrelationFetchConfig = CorrelationFetchConfig()
    morning_report_prompt: str = """Jesteś moim osobistym analitykiem systemów życiowych. Twoim zadaniem jest synteza surowych danych (metryki, notatki, kalendarz), aby pomóc mi zrozumieć, jak mój system działa w kontekście codziennych zobowiązań. Analizuj dane, aby wykrywać konflikty (np. między moim stanem a planami), sugerować zmiany w harmonogramie i mentalnie przygotować mnie na nadchodzący dzień.

    Obecnie jest {current_datetime}. Dzisiaj to {current_day}, wczoraj to {yesterday}.

    Na podstawie dostarczonych danych wygeneruj **Poranny Brief Strategiczny** w formie płynnej narracji (NIE punktów). Raport powinien być jednym ciągłym tekstem podzielonym na akapity, łatwym do szybkiego przeczytania.

    Struktura narracji:
    1.  **Kontekst systemowy** - Jaki jest obecny stan mojego systemu w kontekście dzisiejszego kalendarza? Połącz dane ze snu, body battery i stresu z nadchodzącymi wydarzeniami, aby określić moją gotowość na planowane wyzwania i pomóc mi mentalnie się przygotować.
    2.  **Wzorzec w tle** - Jakie nieoczywiste połączenia widzisz między wczorajszymi wydarzeniami z kalendarza, danymi z Garmina i zapiskami? Wykorzystaj przeszłe wydarzenia do wykrycia trendów i wyjaśnienia dzisiejszego stanu regeneracji.
    3.  **Centralny insight** - Jaki jest jeden kluczowy wniosek, który wynika z korelacji (lub jej braku) między moim stanem wewnętrznym (Garmin) a zewnętrznymi wymaganiami (kalendarz)? Jeśli zapowiada się męczący dzień, a dane wskazują na zmęczenie, zidentyfikuj to jako centralny konflikt.
    4.  **Punkt dźwigni** - Gdzie leży dziś najbardziej efektywna interwencja? Wskaż konkretny moment w dzisiejszym planie, gdzie mała zmiana może przynieść największą korzyść. Może to być sugestia przełożenia spotkania, zmiana kolejności zadań lub wskazówka, jak zmniejszyć negatywny wpływ danego wydarzenia.
    5.  **Perspektywa długoterminowa** - Jak dzisiejszy stan i potencjalna interwencja wpasowują się w moje szersze cele i wzorce z `persistent_memory`? Czy dzisiejszy kalendarz wspiera te cele?

    KLUCZOWE ZASADY:
    - Pisz jednym ciągłym tekstem z podziałem na akapity.
    - Używaj minimalnego formatowania markdown.
    - Myśl systemowo - szukaj połączeń i konfliktów między kalendarzem, notatkami i metrykami.
    - Bądź konkretny i oparty na danych. Każdy insight musi wynikać z dostarczonych danych.
    - Priorytetuj insights z notatek i sprzeczności między danymi.
    - Unikaj pouczającego tonu - jesteś obserwatorem i strategiem, nie nauczycielem.
    - Mów wprost, bez przeprosin że jesteś AI czy zastrzeżeń.
    - Dostarczaj prawdziwe "aha moments" - coś, czego sam bym nie zauważył.

    NIE UŻYWAJ:
    - List punktowych (•, -, 1., 2., etc.)
    - Sekcji z nagłówkami ###
    - Fraz typu "Twoje dane pokazują..."
    - Generycznych porad niezwiązanych z konkretnymi danymi.

    PAMIĘTAJ: To ma być insight newsletter do planowania dnia, nie lista zadań. Pomagasz widzieć wzorce, aby lepiej nawigować nadchodzący dzień.

    ---

    Poniżej znajdują się dane wejściowe w formacie XML. Zwróć szczególną uwagę na tag `<calendar_events>`.

    {data}
    """  # noqa: E501
    # Retry configuration for Garmin data export
    garmin_export_max_retries: int = 5
    garmin_export_retry_delay: float = 30.0  # seconds between retries
    garmin_export_backoff_multiplier: float = 2.0  # exponential backoff multiplier


@dataclass
class GarminDailyMetrics:
    # Sleep (most recent night)
    sleep_score: int
    sleep_time_s: int
    deep_s: int
    light_s: int
    rem_s: int
    restless_cnt: int
    avg_overnight_hrv: Optional[float]

    # Body Battery (current state)
    bb_current: int
    bb_delta_sleep: int

    # Multi-day data for each day in the look-back period
    daily_data: list[DailyMetrics]

    # All activities data for the period
    activities: list[Activity]


class MorningReportService:
    """Encapsulates the entire morning-report generation pipeline."""

    def __init__(
        self,
        morning_report_config: MorningReportConfig,
        obsidian_service: ObsidianService,
        db_service: DBService,
        tz: ZoneInfo,
        garmin_data_exporter: InfluxDBGarminDataExporter,
        calendar_service: CalendarService,
    ) -> None:
        self.cfg = morning_report_config
        self.garmin_data_exporter = garmin_data_exporter
        self.summary_llm = LLMService(self.cfg.summarizing_llm_config)
        self.obsidian_service = obsidian_service
        self.calendar_service = calendar_service
        self.db_service = db_service
        self._TZ = tz

    async def create_morning_summary(self, user_id: int | None = None) -> str:  # noqa: D401
        """Return Markdown report ready to send to Telegram.

        *`user_id` is accepted for future multi-user routing but not used yet.*
        """
        logger.info("🏗  Building morning report (⟲{} d)…", self.cfg.number_of_days)

        # Export Garmin data with retry logic
        garmin_summary = await self._export_garmin_data_with_retry()

        logger.debug("📝 Loading daily notes...")
        notes_by_date = await self._get_latest_daily_notes()
        logger.debug("🧠 Loading persistent memory...")
        persistent_memory = await self.obsidian_service.get_persistent_memory_content()
        logger.debug("📅 Loading calendar data...")
        calendar_data = await self._get_calendar_context()
        logger.debug("📈 Loading correlation insights...")
        correlation_data = await self._get_recent_correlations()

        logger.debug("🛠 Building prompt...")
        prompt = self._build_prompt(
            garmin_summary=garmin_summary,
            notes_by_date=notes_by_date,
            persistent_memory=persistent_memory,
            calendar_data=calendar_data,
            correlation_data=correlation_data,
        )

        logger.debug("Prompt length: {} chars", len(prompt))

        logger.debug("🧠 Calling LLM...")
        report = await self.summary_llm.aprompt_llm(prompt)
        report = clean_ai_response(report)
        logger.success("✅ Morning report ready ({} chars)", len(report))

        # Save the morning report to today's AI log
        today = datetime.now(tz=self._TZ).date()
        try:
            await self.obsidian_service.add_ai_log_entry(today, report, "morning_report")
            logger.debug("📝 Morning report saved to today's AI log")
        except Exception as e:
            logger.warning(f"⚠️ Failed to save morning report to AI log: {e}")

        return report

    async def _export_garmin_data_with_retry(self) -> Optional[GarminDailyMetrics]:
        """Export Garmin data with retry logic and exponential backoff."""
        last_exception = None
        delay = self.cfg.garmin_export_retry_delay

        for attempt in range(1, self.cfg.garmin_export_max_retries + 1):
            try:
                if attempt == 1:
                    logger.info("📥 Exporting Garmin data...")
                else:
                    logger.info(
                        "🔄 Retrying Garmin data export (attempt {}/{})", attempt, self.cfg.garmin_export_max_retries
                    )
                await self.garmin_data_exporter.refresh_influxdb_data(start_date=date.today())
                raw_garmin = await self.garmin_data_exporter.export_data(days=self.cfg.number_of_days)
                logger.debug("📊 Processing Garmin data...")
                garmin_summary = self._preprocess_garmin(raw_garmin)
                logger.debug("✅ Garmin data processed successfully")
                return garmin_summary

            except subprocess.SubprocessError as e:
                last_exception = e
                logger.warning(
                    "⚠️ Garmin data export failed (attempt {}/{}): {}", attempt, self.cfg.garmin_export_max_retries, e
                )

                if attempt < self.cfg.garmin_export_max_retries:
                    logger.info("⏳ Waiting {:.1f}s before retry (sleep data may not be ready yet)...", delay)
                    await asyncio.sleep(delay)
                    delay *= self.cfg.garmin_export_backoff_multiplier

            except Exception as e:
                last_exception = e
                logger.warning(
                    "⚠️ Failed to process Garmin data (attempt {}/{}): {}",
                    attempt,
                    self.cfg.garmin_export_max_retries,
                    e,
                )

                if attempt < self.cfg.garmin_export_max_retries:
                    logger.info("⏳ Waiting {:.1f}s before retry...", delay)
                    await asyncio.sleep(delay)
                    delay *= self.cfg.garmin_export_backoff_multiplier

        # All retries failed
        logger.error(
            "❌ Failed to export Garmin data after {} attempts. Last error: {}",
            self.cfg.garmin_export_max_retries,
            last_exception,
        )
        return None

    def _parse_activities(self, activity_summary_df: Optional[pd.DataFrame]) -> dict[date, list[Activity]]:
        """Parse and clean activity data into Activity models."""
        if activity_summary_df is None or activity_summary_df.empty:
            logger.warning("⚠️ Activity summary data is missing or empty.")
            return {}

        activities_by_date = {}
        for _, row in activity_summary_df.iterrows():
            activity_name = (row.get("activityName") or row.get("activityType") or "Unknown").strip()
            calories = int(row.get("calories", 0)) if pd.notna(row.get("calories", 0)) else 0
            duration_min = int(row.get("elapsedDuration", 0) / 60) if pd.notna(row.get("elapsedDuration", 0)) else 0

            # Skip termination markers or activities with no data
            if activity_name.upper() == "END" or (calories == 0 and duration_min == 0):
                continue

            start_time_raw = row.get("startTimeLocal") or row.get("time")
            if not start_time_raw:
                logger.warning(f"Skipping activity '{activity_name}' due to missing start time.")
                continue

            try:
                if isinstance(start_time_raw, str):
                    if start_time_raw.endswith("Z"):
                        dt = datetime.fromisoformat(start_time_raw.replace("Z", "+00:00"))
                    elif "+" in start_time_raw or "-" in start_time_raw[-6:]:
                        dt = datetime.fromisoformat(start_time_raw)
                    else:
                        # Assume UTC if no timezone info
                        dt = datetime.fromisoformat(start_time_raw).replace(tzinfo=timezone.utc)
                else:
                    dt = start_time_raw

                # Convert to local date
                local_dt = dt.astimezone(self._TZ)
                activity_date = local_dt.date()
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse date for activity '{activity_name}' with time '{start_time_raw}': {e}")
                continue

            distance_m = row.get("distance")
            distance_km = float(distance_m / 1000) if pd.notna(distance_m) and distance_m > 0 else None

            activity = Activity(
                name=activity_name,
                calories=calories,
                duration_min=duration_min,
                avg_hr=int(row.get("averageHR")) if pd.notna(row.get("averageHR")) else None,
                start_time=local_dt.isoformat(),
                distance_km=distance_km,
            )

            activities_by_date.setdefault(activity_date, []).append(activity)
            logger.debug(f"✅ Added activity '{activity_name}' to date {activity_date}")

        return activities_by_date

    def _process_daily_metrics(
        self,
        daily_df: pd.DataFrame,
        bb_df: Optional[pd.DataFrame],
        hr_df: Optional[pd.DataFrame],
        activities_by_date: dict[date, list[Activity]],
        start_date: date,
        end_date: date,
    ) -> list[DailyMetrics]:
        """Aggregate daily stats into DailyMetrics models."""
        processed_metrics = []

        # Ensure date columns are in the correct format for merging/lookup
        if "calendarDate" in daily_df.columns:
            daily_df = daily_df.copy()
            daily_df["date"] = pd.to_datetime(daily_df["calendarDate"]).dt.date

        if bb_df is not None and not bb_df.empty:
            bb_df = bb_df.copy()
            bb_df["local"] = pd.to_datetime(bb_df["time"], utc=True, errors="coerce").dt.tz_convert(self._TZ)
            bb_df = bb_df.dropna(subset=["local"])
            bb_df["date"] = bb_df["local"].dt.date

        if hr_df is not None and not hr_df.empty:
            hr_df = hr_df.copy()
            hr_df["local"] = pd.to_datetime(hr_df["time"], utc=True, errors="coerce").dt.tz_convert(self._TZ)
            hr_df = hr_df.dropna(subset=["local"])
            hr_df["date"] = hr_df["local"].dt.date

        current_date = start_date
        while current_date <= end_date:
            if "date" in daily_df.columns:
                day_stats = daily_df[daily_df["date"] == current_date]
            else:
                # If no date column, assume the data is ordered and take the appropriate row
                days_from_end = (end_date - current_date).days
                if days_from_end < len(daily_df):
                    day_stats = (
                        daily_df.iloc[-(days_from_end + 1) : -days_from_end]
                        if days_from_end > 0
                        else daily_df.iloc[-1:]
                    )
                else:
                    day_stats = pd.DataFrame()

            if day_stats.empty:
                current_date += timedelta(days=1)
                continue

            day_row = day_stats.iloc[0]

            day_bb = bb_df[bb_df["date"] == current_date] if bb_df is not None else pd.DataFrame()
            day_hr = hr_df[hr_df["date"] == current_date] if hr_df is not None else pd.DataFrame()

            metrics = DailyMetrics(
                date=current_date,
                steps=int(day_row.get("totalSteps", 0)),
                active_kcal=int(day_row.get("activeKilocalories", 0)),
                resting_hr=int(day_row.get("restingHeartRate", 0)),
                hr_min=int(day_hr["HeartRate"].min()) if not day_hr.empty and "HeartRate" in day_hr.columns else 0,
                hr_max=int(day_hr["HeartRate"].max()) if not day_hr.empty and "HeartRate" in day_hr.columns else 0,
                hr_avg=int(day_hr["HeartRate"].mean()) if not day_hr.empty and "HeartRate" in day_hr.columns else 0,
                stress=StressSummary(
                    stress_pct=float(day_row.get("stressPercentage", 0)),
                    low_pct=float(day_row.get("lowStressPercentage", 0)),
                    medium_pct=float(day_row.get("mediumStressPercentage", 0)),
                    high_pct=float(day_row.get("highStressPercentage", 0)),
                ),
                body_battery=BodyBatterySummary(
                    high=int(day_bb["BodyBatteryLevel"].max()) if not day_bb.empty else 0,
                    low=int(day_bb["BodyBatteryLevel"].min()) if not day_bb.empty else 0,
                    avg=int(day_bb["BodyBatteryLevel"].mean()) if not day_bb.empty else 0,
                ),
                activities=activities_by_date.get(current_date, []),
            )
            processed_metrics.append(metrics)
            current_date += timedelta(days=1)

        return processed_metrics

    async def _get_latest_daily_notes(self) -> dict[str, str]:
        """Get daily notes grouped by date using ObsidianService."""
        return await self.obsidian_service.get_recent_daily_notes(self.cfg.number_of_days)

    async def _get_calendar_context(self) -> Optional[str]:
        """Get calendar events and reminders for the configured lookback/lookahead period."""
        today = datetime.now(tz=self._TZ).date()
        start_date = today - timedelta(days=self.cfg.calendar_lookback_days)
        end_date = today + timedelta(days=self.cfg.calendar_lookahead_days)

        query = CalendarEventQuery(
            start_date=start_date,
            end_date=end_date,
            include_all_day=True,
            include_reminders=True,
        )
        calendar_result = await self.calendar_service.get_events(query)
        return self.calendar_service.format_events_for_context(calendar_result)

    async def _get_recent_correlations(self) -> Optional[str]:
        """Fetch and format correlation insights for morning report.

        Returns None if no data available or on recoverable errors.
        Raises on unrecoverable errors that should halt execution.
        """
        import sqlite3

        try:
            records = await asyncio.to_thread(
                self.db_service.fetch_correlation_events,
                lookback_days=self.cfg.correlation_fetch.lookback_days,
                limit=self.cfg.correlation_fetch.max_events,
            )
        except sqlite3.DatabaseError as exc:
            # Database corruption or serious DB errors - should not continue
            logger.error("⚠️ Database error loading correlation events: {}", exc)
            raise
        except (ValueError, TypeError) as exc:
            # Invalid configuration or data format - likely a bug
            logger.error("⚠️ Invalid data or configuration for correlation fetch: {}", exc)
            raise
        except Exception as exc:
            # Unexpected errors - log and continue without correlation data
            logger.warning("⚠️ Unexpected error loading correlation events: {}", exc)
            return None

        summary = format_correlation_events(records, tz=self._TZ)
        return summary if summary else None

    def _preprocess_garmin(self, data: GarminExportData) -> GarminDailyMetrics:
        """Orchestrate the Garmin data transformation."""
        logger.debug("🔄 Starting Garmin data preprocessing...")

        if data.sleep_summary is None or data.sleep_summary.empty:
            raise ValueError("SleepSummary missing – cannot generate report")
        if data.daily_stats is None or data.daily_stats.empty:
            raise ValueError("DailyStats missing – cannot generate report")

        today = datetime.now(tz=self._TZ).date()
        end_date = today
        start_date = end_date - timedelta(days=self.cfg.number_of_days - 1)

        activities_by_date = self._parse_activities(data.activity_summary)

        daily_metrics = self._process_daily_metrics(
            daily_df=data.daily_stats,
            bb_df=data.body_battery_intraday,
            hr_df=data.heart_rate_intraday,
            activities_by_date=activities_by_date,
            start_date=start_date,
            end_date=end_date,
        )

        last_sleep = data.sleep_summary.iloc[-1]
        bb_current = 0
        if data.body_battery_intraday is not None and not data.body_battery_intraday.empty:
            bb_current = int(data.body_battery_intraday.iloc[-1]["BodyBatteryLevel"])

        all_activities = [act for activities in activities_by_date.values() for act in activities]

        result = GarminDailyMetrics(
            sleep_score=int(last_sleep["sleepScore"]),
            sleep_time_s=int(last_sleep["sleepTimeSeconds"]),
            deep_s=int(last_sleep["deepSleepSeconds"]),
            light_s=int(last_sleep["lightSleepSeconds"]),
            rem_s=int(last_sleep["remSleepSeconds"]),
            restless_cnt=int(last_sleep["restlessMomentsCount"]),
            avg_overnight_hrv=float(last_sleep.get("avgOvernightHrv", 0)) or None,
            bb_current=bb_current,
            bb_delta_sleep=int(last_sleep.get("bodyBatteryChange", 0)),
            daily_data=daily_metrics,
            activities=all_activities,
        )

        logger.debug("✅ Garmin preprocessing completed successfully")
        return result

    def _build_prompt(
        self,
        *,
        garmin_summary: GarminDailyMetrics | None,
        notes_by_date: dict[str, str],
        persistent_memory: str,
        calendar_data: Optional[str],
        correlation_data: Optional[str],
    ) -> str:
        """Prepare the full system + user prompt for the LLM with XML-structured data by date."""
        current_datetime = datetime.now(tz=self._TZ).strftime("%Y-%m-%d %H:%M")
        today = datetime.now(tz=self._TZ).date()
        yesterday = today - timedelta(days=1)

        # Get all unique dates from notes, and garmin data
        all_dates = set(notes_by_date.keys())

        # Add dates from garmin data if available
        if garmin_summary and garmin_summary.daily_data:
            garmin_dates = {day_data.date.isoformat() for day_data in garmin_summary.daily_data}
            all_dates.update(garmin_dates)

        # Sort dates in descending order (most recent first)
        sorted_dates = sorted(all_dates, reverse=True)

        # Build XML-structured data by date
        data_blocks = []

        # Add persistent memory first if available
        if persistent_memory and persistent_memory.strip():
            data_blocks.append(f"<persistent_memory>\n{persistent_memory.strip()}\n</persistent_memory>")

        # Add current sleep and body battery status first if available
        if garmin_summary:
            sleep_block = format_current_sleep_status_md(garmin_summary, self._TZ)
            if sleep_block:
                data_blocks.append(f"<current_status>\n{sleep_block}\n</current_status>")

        # Add calendar events and reminders
        if calendar_data and calendar_data.strip():
            data_blocks.append(f"<calendar_events>\n{calendar_data.strip()}\n</calendar_events>")

        if correlation_data:
            correlation_block = correlation_data.strip()
            if correlation_block:
                data_blocks.append(f"<correlations>\n{correlation_block}\n</correlations>")

        for day in sorted_dates:
            date_block = f"<data_for_{day}>"

            # Add daily note for this date
            if day in notes_by_date:
                date_block += f"\n<daily_note>\n{notes_by_date[day]}\n</daily_note>"

            # Add Garmin data for this date with markdown formatting
            if garmin_summary and garmin_summary.daily_data:
                day_as_date = date.fromisoformat(day)
                garmin_day_data = next((g for g in garmin_summary.daily_data if g.date == day_as_date), None)
                if garmin_day_data:
                    garmin_markdown = format_garmin_day_markdown_md(garmin_day_data, self._TZ)
                    date_block += f"\n<garmin_data>\n{garmin_markdown}\n</garmin_data>"

            date_block += f"\n</data_for_{day}>"
            data_blocks.append(date_block)

        # Combine all data blocks
        data = "\n\n".join(data_blocks)

        return self.cfg.morning_report_prompt.format(
            data=data, current_datetime=current_datetime, current_day=today.isoformat(), yesterday=yesterday.isoformat()
        )
