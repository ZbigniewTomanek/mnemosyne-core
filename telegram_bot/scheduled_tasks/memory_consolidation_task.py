"""Memory Consolidation Scheduled Task

Configures and schedules the weekly memory consolidation task that:
1. Consolidates weekly AI memory & daily notes into weekly summaries
2. Extracts and manages persistent facts from interaction logs
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, Optional

import yaml
from loguru import logger
from pydantic import BaseModel, Field
from telegram import Bot

from telegram_bot.constants import DefaultLLMConfig
from telegram_bot.service.background_task_executor import TaskResult
from telegram_bot.service.llm_service import LLMConfig
from telegram_bot.service.persistent_memory.document import PersistentMemoryDocument
from telegram_bot.service.persistent_memory.llm_models import PersistentMemoryLLMResponse
from telegram_bot.service.persistent_memory.service import (
    FileSystemPersistentMemoryRepository,
    PersistentMemoryUpdater,
    SectionRoutingConfig,
)

if TYPE_CHECKING:
    from telegram_bot.service.llm_service import LLMService
    from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig, ObsidianService
    from telegram_bot.service.scheduled_task_service import ScheduledTaskService


class WeeklySummaryReflectiveOutput(BaseModel):
    """Structured and reflective output from LLM for weekly summaries."""

    wazne_wydarzenia: list[str]
    refleksja_samopoczucie: str
    refleksja_sny: Optional[str] = None
    refleksja_zdrowie: str
    refleksja_praca: str
    refleksja_co_sie_zmienia: str
    refleksja_co_bylo_przyjemne: list[str]
    refleksja_co_bylo_nieprzyjemne: list[str]
    refleksja_co_poszlo_zle: str


def _default_persistent_section_routing() -> dict[str, str]:
    return {
        "health": "Zdrowie i Samopoczucie",
        "health_routine": "Zdrowie i Samopoczucie",
        "habit": "Zdrowie i Samopoczucie",
        "wellbeing": "Zdrowie i Samopoczucie",
        "productivity": "Praca i Produktywność",
        "work": "Praca i Produktywność",
        "project": "Projekty Osobiste",
        "project_deadline": "Projekty Osobiste",
        "preference": "Relacje i Kontakty",
        "contact_info": "Relacje i Kontakty",
        "relationship": "Relacje i Kontakty",
        "hobby": "Hobby i Zainteresowania",
        "interest": "Hobby i Zainteresowania",
        "finance": "Finanse",
        "financial": "Finanse",
        "system_usage": "Systemy i Narzędzia",
        "tool": "Systemy i Narzędzia",
        "travel": "Podróże",
    }


class MemoryConsolidationTaskConfig(BaseModel):
    """Configuration for the memory consolidation scheduled task."""

    enabled: bool = True
    schedule_time: str = "0 2 * * 1"  # Monday at 2:00 AM (cron format)
    target_user_id: int = int(os.getenv("MY_TELEGRAM_USER_ID", "0"))

    weekly_memory_dir: str = "30 AI Assistant/memory"
    persistent_memory_file: str = "30 AI Assistant/memory/persistent_memory.md"
    ai_logs_dir: str = "30 AI Assistant/memory/logs"
    daily_notes_dir: str = "01 management/10 process/0 daily"

    summarization_llm_config: LLMConfig = DefaultLLMConfig.GEMINI_PRO
    fact_extraction_llm_config: LLMConfig = DefaultLLMConfig.GEMINI_PRO

    days_to_process_for_weekly: int = 7

    persistent_memory_default_section: str = "Projekty Osobiste"
    persistent_memory_section_routing: dict[str, str] = Field(default_factory=_default_persistent_section_routing)

    weekly_summary_prompt: str = """Jesteś moim osobistym, analitycznym asystentem i "drugim mózgiem". Twoim zadaniem jest przeanalizowanie moich notatek dziennych z ostatniego tygodnia i wygenerowanie ustrukturyzowanego podsumowania, które pomoże mi w cotygodniowej refleksji.

Przeanalizuj poniższe notatki krok po kroku. Zwróć szczególną uwagę na powiązania między wydarzeniami, moim samopoczuciem (fizycznym i psychicznym), poziomem energii, pracą i życiem osobistym. Bądź zwięzły, ale konkretny, odwołując się do detali z notatek.

<dane_wejsciowe>
{combined_content}
</dane_wejsciowe>

Twoim zadaniem jest wygenerowanie odpowiedzi w formacie JSON, która ściśle odpowiada poniższej strukturze. Wypełnij każdą sekcję na podstawie dostarczonych notatek.

<struktura_wyjsciowa>
{
  "wazne_wydarzenia": [
    "Krótki opis pierwszego ważnego wydarzenia (np. 'Finalizacja projektu transkrypcji w pracy').",
    "Krótki opis drugiego ważnego wydarzenia (np. 'Stresująca sytuacja z organizacją opieki nad kotami przed wyjazdem na Hel').",
    "Krótki opis trzeciego ważnego wydarzenia (np. 'Wyjazd na Hel z Ewą')."
  ],
  "refleksja_samopoczucie": "Syntetyczna odpowiedź na pytanie: Jakie było moje ogólne samopoczucie i poziom energii w tym tygodniu? Zwróć uwagę na wahania i możliwe przyczyny (np. problemy z zatokami, wpływ snu, reakcja na alkohol).",
  "refleksja_sny": "Podsumowanie kluczowych snów z tygodnia, jeśli zostały zanotowane. Jeśli nie, zostaw to pole puste.",
  "refleksja_zdrowie": "Podsumowanie mojego stanu zdrowia fizycznego. Wymień konkretne dolegliwości (np. problemy żołądkowe, objawy przeziębienia, ból zęba) i pozytywne aspekty (np. udany trening, poczucie regeneracji po dobrym śnie).",
  "refleksja_praca": "Podsumowanie kluczowych wydarzeń i emocji związanych z pracą. Wymień sukcesy (np. rozwiązanie problemu z GPU), frustracje (np. problemy z raportami, irytacja na design MCP) i postępy.",
  "refleksja_co_sie_zmienia": "Wskaż na zmiany w moim zachowaniu, samopoczuciu lub rutynie, które zaobserwowałeś w tym tygodniu (np. 'Po odstawieniu SSRI Twoje stany emocjonalne stały się bardziej intensywne', 'Reakcja na alkohol uległa zmianie').",
  "refleksja_co_bylo_przyjemne": "Wylistuj 2-3 konkretne, przyjemne momenty lub aktywności wspomniane w notatkach (np. 'Wieczorna sesja rozciągania PNF', 'Udany trening wspinaczkowy', 'Spokojny dzień na plaży na Helu').",
  "refleksja_co_bylo_nieprzyjemne": "Wylistuj 2-3 konkretne, nieprzyjemne momenty lub źródła stresu (np. 'Irytacja podczas przeglądania refinementu MCP', 'Stres związany z opieką nad kotami', 'Złe samopoczucie po wypiciu piwa').",
  "refleksja_co_poszlo_zle": "Wskaż na konkretne sytuacje, które poszły nie tak i które można by poprawić (np. 'Niezrozumienie z Martynką w sprawie opieki nad kotami wskazuje na potrzebę bardziej precyzcyjej komunikacji i potwierdzania ustaleń')."
}
</struktura_wyjsciowa>

Pamiętaj, aby odpowiedź była w języku polskim i gotowa do umieszczenia w moim pliku z tygodniowym podsumowaniem."""  # noqa: E501

    fact_extraction_prompt: str = """Jesteś AI asystentem odpowiedzialnym za utrzymanie długoterminowej pamięci użytkownika.

Twoim celem jest porównanie nowych informacji z tygodnia z aktualną pamięcią persistent i wygenerowanie prawdziwego diffu:
- jeśli informacja uzupełnia istniejący fakt, zaktualizuj go (`update`) zachowując identyfikator,
- jeśli informacja zmienia status lub opis istniejącego faktu, zaktualizuj odpowiednie pola,
- jeśli informacja jest już aktualna, pomiń ją (nie twórz duplikatów),
- jeśli fakt przestał być prawdziwy, umieść jego identyfikator na liście `remove`,
- tylko gdy brak dopasowania do istniejących faktów, dodaj nowy wpis do `add`.

Zakres faktów do utrzymania:
- trwałe lub długoterminowe informacje o zdrowiu, zwyczajach, projektach, finansach, relacjach,
- preferencje, cele, ograniczenia, ważne osoby oraz systemy wykorzystywane przez użytkownika.

Pominięcia:
- jednorazowe wydarzenia,
- chwilowe stany bez długoterminowych konsekwencji,
- szczegóły dzienników, które nie zmieniają żadnego faktu.

Nazwy sekcji muszą pochodzić z listy:
- "Zdrowie i Samopoczucie"
- "Praca i Produktywność"
- "Relacje i Kontakty"
- "Hobby i Zainteresowania"
- "Projekty Osobiste"
- "Finanse"
- "Systemy i Narzędzia"
- "Podróże"

Pola `first_seen` i `last_seen` zapisuj jako daty `YYYY-MM-DD`, jeżeli są dostępne. Pole `sources` wypełnij unikalnymi nazwami notatek, które potwierdzają fakt. W sekcji `update` zachowuj istniejące identyfikatory i zmieniaj tylko te pola, które wymagają korekty.

AKTUALNA PAMIĘĆ PERSISTENT (tylko do odczytu — nie modyfikuj jej bezpośrednio):
{current_memory}

DANE DO ANALIZY (nowe obserwacje z tygodnia):
{combined_content}

Odpowiedz w formacie JSON zgodnie z poniższym schematem i zachowaj wszystkie klucze nawet, jeśli listy pozostają puste:

<schemat_wyjsciowy>
{
  "sections": [
    {
      "name": "Zdrowie i Samopoczucie",
      "add": [
        {
          "statement": "Nowy fakt wymagający zapisania",
          "category": "health",
          "confidence": 0.85,
          "first_seen": "2024-05-20",
          "last_seen": "2024-05-20",
          "sources": ["2024-05-20_ai_log"],
          "status": "active",
          "notes": "opcjonalne dodatkowe informacje"
        }
      ],
      "update": [
        {
          "id": "health-1",
          "statement": "Zaktualizowana wersja istniejącego faktu",
          "category": "health",
          "confidence": 0.95,
          "first_seen": "2024-04-01",
          "last_seen": "2024-05-20",
          "sources": ["2024-04-15_ai_log", "2024-05-20_note"],
          "status": "active",
          "notes": "opcjonalne"
        }
      ],
      "remove": ["work-1"]
    }
  ]
}
</schemat_wyjsciowy>

Upewnij się, że każdy fakt trafia dokładnie do jednej sekcji. Korzystaj z sekcji `update` zawsze wtedy, gdy treść pokrywa się z istniejącym wpisem (nawet jeśli zmienia się tylko fragment notatki). Jeśli w danej sekcji brak zmian, zwróć pustą listę `sections` lub pozostaw listy `add`/`update`/`remove` puste."""  # noqa: E501


def _perform_memory_consolidation(
    memory_consolidation_config_dict: dict[str, Any],
    obsidian_config_dict: dict[str, Any],
) -> dict[str, Any]:
    """Perform memory consolidation - sync function that can be pickled.

    Args:
        memory_consolidation_config_dict: Serialized config dict for MemoryConsolidationTaskConfig
        obsidian_config_dict: Serialized config dict for ObsidianConfig

    Returns:
        Dictionary with consolidation results
    """
    import asyncio

    from telegram_bot.service.llm_service import LLMService
    from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig, ObsidianService

    memory_config = MemoryConsolidationTaskConfig(**memory_consolidation_config_dict)
    obsidian_config = ObsidianConfig(**obsidian_config_dict)
    obsidian_service = ObsidianService(obsidian_config)

    # Initialize LLM services
    summary_llm = LLMService(memory_config.summarization_llm_config)
    fact_llm = LLMService(memory_config.fact_extraction_llm_config)

    # Run the consolidation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _run_consolidation_logic(memory_config, obsidian_service, summary_llm, fact_llm)
        )
        return result
    finally:
        loop.close()


async def _run_consolidation_logic(  # noqa: C901
    config: MemoryConsolidationTaskConfig,
    obsidian_service: "ObsidianService",
    summary_llm: "LLMService",
    fact_llm: "LLMService",
) -> dict[str, Any]:
    """Core consolidation logic."""
    # Europe/Warsaw timezone
    tz = timezone(timedelta(hours=2))
    today = datetime.now(tz=tz).date()

    # Calculate previous week (Monday to Sunday)
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)

    logger.info(f"Processing memory consolidation for week {last_monday} to {last_sunday}")

    # Get ISO week number for filename
    year, week_num, _ = last_monday.isocalendar()

    daily_notes_content = {}

    current_date = last_monday
    while current_date <= last_sunday:
        date_str = current_date.isoformat()

        daily_note_path = obsidian_service.get_daily_note_path(current_date)
        if daily_note_path.exists():
            try:
                content = await obsidian_service.safe_read_file(daily_note_path)
                daily_notes_content[date_str] = content
                logger.debug(f"Loaded daily note for {date_str}")
            except Exception as e:
                logger.warning(f"Failed to read daily note for {date_str}: {e}")

        current_date += timedelta(days=1)

    # Combine all content for analysis
    combined_content = _format_content(daily_notes_content)

    if not combined_content.strip():
        logger.warning("No content found for the week, skipping consolidation")
        return {"status": "skipped", "reason": "no_content"}

    # Generate weekly summary using LLM
    logger.info("Generating weekly summary with LLM...")
    # Use safe replacement instead of str.format to avoid KeyError from JSON braces in prompt
    summary_prompt = config.weekly_summary_prompt.replace("{combined_content}", combined_content)

    try:
        # Używamy nowego, bardziej szczegółowego modelu Pydantic
        weekly_summary = await summary_llm.aprompt_llm_with_structured_output(
            summary_prompt, WeeklySummaryReflectiveOutput
        )
        logger.success("Weekly summary generated successfully")
    except Exception as e:
        logger.error(f"Failed to generate weekly summary: {e}")
        return {"status": "error", "error": str(e)}

    # Load current persistent memory snapshot for diff-aware fact extraction
    persistent_file_path = obsidian_service.get_persistent_memory_path(config.persistent_memory_file)

    try:
        persistent_raw = await obsidian_service.safe_read_file(persistent_file_path)
        persistent_document = PersistentMemoryDocument.parse(persistent_raw)
    except FileNotFoundError:
        logger.info("No existing persistent memory file found, using empty snapshot")
        persistent_raw = ""
        persistent_document = PersistentMemoryDocument(frontmatter={}, sections=())
    except Exception as exc:
        logger.error(f"Failed to load persistent memory for diffing: {exc}")
        return {"status": "error", "error": str(exc)}

    persistent_memory_snapshot = _format_persistent_memory_snapshot(persistent_document)

    # Extract persistent memory delta using LLM
    logger.info("Extracting persistent memory delta with LLM...")
    fact_prompt = config.fact_extraction_prompt
    fact_prompt = fact_prompt.replace("{current_memory}", persistent_memory_snapshot)
    fact_prompt = fact_prompt.replace("{combined_content}", combined_content)

    try:
        persistent_response = await fact_llm.aprompt_llm_with_structured_output(
            fact_prompt, PersistentMemoryLLMResponse
        )
        section_deltas = persistent_response.to_domain_deltas()
        logger.success("Persistent memory delta generated successfully")
    except Exception as e:
        logger.error(f"Failed to extract persistent memory delta: {e}")
        section_deltas = {}

    filtered_deltas = {
        name: delta for name, delta in section_deltas.items() if delta.additions or delta.updates or delta.removals
    }

    additions_count = sum(len(delta.additions) for delta in filtered_deltas.values())
    updates_count = sum(len(delta.updates) for delta in filtered_deltas.values())
    removals_count = sum(len(delta.removals) for delta in filtered_deltas.values())

    # Save weekly summary
    weekly_file_path = obsidian_service.get_weekly_memory_path(year, week_num, config.weekly_memory_dir)
    weekly_content = _format_weekly_summary_content(
        weekly_summary, last_monday, last_sunday, daily_notes_content, obsidian_service
    )

    try:
        await obsidian_service.safe_write_file(weekly_file_path, weekly_content)
        logger.success(f"Weekly summary saved to {weekly_file_path}")
    except Exception as e:
        logger.error(f"Failed to save weekly summary: {e}")
        return {"status": "error", "error": str(e)}

    # Update persistent memory
    persistent_update_summary: dict[str, dict[str, int]] = {}

    if filtered_deltas:

        async def loader() -> str:
            return persistent_raw

        async def saver(content: str) -> None:
            await obsidian_service.safe_write_file(persistent_file_path, content)

        repository = FileSystemPersistentMemoryRepository(loader=loader, saver=saver)
        updater = PersistentMemoryUpdater(
            repository=repository,
            routing=SectionRoutingConfig(
                category_to_section=config.persistent_memory_section_routing,
                default_section=config.persistent_memory_default_section,
            ),
        )

        try:
            await updater.update(filtered_deltas)
            persistent_update_summary = updater.last_summary
            logger.success(
                "Persistent memory updated: {} additions, {} updates, {} removals",
                additions_count,
                updates_count,
                removals_count,
            )
        except Exception as e:
            logger.error(f"Failed to update persistent memory: {e}")
    else:
        logger.info("No persistent memory changes detected")

    return {
        "status": "success",
        "weekly_file": str(weekly_file_path),
        "persistent_file": str(persistent_file_path),
        "facts_extracted": additions_count,
        "facts_updated": updates_count,
        "facts_removed": removals_count,
        "persistent_memory_delta": persistent_update_summary,
        "week_processed": f"{last_monday} to {last_sunday}",
    }


def _format_content(daily_notes: dict[str, str]) -> str:
    """Format combined content from AI logs and daily notes."""
    content_blocks = []

    # Get all dates and sort them
    all_dates = set(daily_notes.keys())
    sorted_dates = sorted(all_dates)

    for date_str in sorted_dates:
        date_block = f"=== {date_str} ==="

        if date_str in daily_notes:
            date_block += f"\n\n[NOTATKA DZIENNA]\n{daily_notes[date_str]}"

        content_blocks.append(date_block)

    return "\n\n".join(content_blocks)


def _format_persistent_memory_snapshot(document: PersistentMemoryDocument) -> str:
    """Create a compact JSON snapshot of the current persistent memory for LLM context."""

    sections_payload: dict[str, list[dict[str, object]]] = {}
    for section in document.sections:
        facts_payload: list[dict[str, object]] = []
        for fact in section.facts:
            facts_payload.append(
                {
                    "id": fact.id,
                    "statement": fact.statement,
                    "category": fact.category,
                    "status": fact.status,
                    "notes": fact.notes,
                    "confidence": fact.confidence,
                    "first_seen": fact.first_seen.isoformat() if fact.first_seen else None,
                    "last_seen": fact.last_seen.isoformat() if fact.last_seen else None,
                    "sources": list(fact.sources),
                }
            )
        sections_payload[section.name] = facts_payload

    snapshot = {"sections": sections_payload}
    return json.dumps(snapshot, ensure_ascii=False, indent=2)


def _format_weekly_summary_content(
    summary: WeeklySummaryReflectiveOutput,
    start_date: date,
    end_date: date,
    daily_notes: dict[str, str],
    obsidian_service: "ObsidianService",
) -> str:
    """Format the weekly summary content for the markdown file using the new reflective structure."""
    year, week_num, _ = start_date.isocalendar()

    # YAML frontmatter (bez zmian)
    frontmatter = {
        "consolidation_type": "weekly",
        "consolidation_date": datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d"),
        "source_logs_start_date": start_date.isoformat(),
        "source_logs_end_date": end_date.isoformat(),
        "consolidated_week": f"{year}-W{week_num:02d}",
        "tags": ["ai_summary", "weekly_reflection", "daily_notes_summary"],
    }
    content = f"---\n{yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)}---\n\n"

    # Nagłówek główny
    content += f"# AI Weekly Reflection - Week {year}-W{week_num:02d}\n\n"
    content += f"**Okres:** {start_date} do {end_date}\n\n"

    # Sekcja: Ważne wydarzenia
    if summary.wazne_wydarzenia:
        content += "## Ważne wydarzenia w tym tygodniu\n\n"
        for event in summary.wazne_wydarzenia:
            content += f"- {event}\n"
        content += "\n---\n"

    # Sekcja: Refleksja
    content += "## Refleksja\n\n"

    content += f"> [!quote] Jak tam samopoczucie w ciągu tego tygodnia?\n> {summary.refleksja_samopoczucie}\n\n"

    if summary.refleksja_sny and summary.refleksja_sny.strip():
        content += f"> [!dream] Co próbowały przekazać sny?\n> {summary.refleksja_sny}\n\n"

    content += f"> [!health] Jak tam zdrówko?\n> {summary.refleksja_zdrowie}\n\n"
    content += f"> [!example] Co tam w pracy?\n> {summary.refleksja_praca}\n\n"
    content += f"> [!NOTE] Co się zmienia?\n> {summary.refleksja_co_sie_zmienia}\n\n"

    if summary.refleksja_co_bylo_przyjemne:
        content += "> [!tip] Co było przyjemne i miało wartość?\n"
        for item in summary.refleksja_co_bylo_przyjemne:
            content += f"> - {item}\n"
        content += "\n"

    if summary.refleksja_co_bylo_nieprzyjemne:
        content += "> [!faq] Co było nieprzyjemne?\n"
        for item in summary.refleksja_co_bylo_nieprzyjemne:
            content += f"> - {item}\n"
        content += "\n"

    content += f"> [!warning] Co poszło źle i można by to poprawić\n> {summary.refleksja_co_poszlo_zle}\n\n"

    content += "---\n"

    # Sekcja: Pliki źródłowe (bez zmian)
    content += "## 📚 Źródłowe Notatki\n\n"
    sorted_dates = sorted(daily_notes.keys())
    for date_str in sorted_dates:
        daily_link = obsidian_service.generate_obsidian_link(date_str)
        content += f"- {daily_link}\n"
    content += "\n"

    return content


async def _memory_consolidation_callback(
    task_result: TaskResult[dict[str, Any]],
    target_user_id: int,
    bot_token: str,
) -> None:
    """Callback to handle the memory consolidation result and send notification.

    Args:
        task_result: Result from the memory consolidation task
        target_user_id: User ID to send notification to
        bot_token: Bot token for sending messages
    """
    from telegram import Bot
    from telegram.error import TelegramError

    bot = Bot(token=bot_token)

    if task_result.exception:
        logger.error("Memory consolidation failed: {}", task_result.exception)
        try:
            await bot.send_message(
                chat_id=target_user_id, text=f"❌ Memory consolidation failed: {task_result.exception}"
            )
        except TelegramError as e:
            logger.error("Failed to send error notification via Telegram: {}", e)
        return

    if not task_result.result:
        logger.error("Memory consolidation returned empty result")
        return

    result = task_result.result

    if result.get("status") == "success":
        message = "✅ Memory consolidation completed successfully!\n\n"
        message += f"📅 Week processed: {result.get('week_processed')}\n"
        message += f"📄 Weekly summary: {result.get('weekly_file', 'N/A')}\n"
        message += f"🧠 Persistent facts: {result.get('facts_extracted', 0)} new facts extracted\n"
        message += f"💾 Updated: {result.get('persistent_file', 'N/A')}"
    elif result.get("status") == "skipped":
        message = f"⚠️ Memory consolidation skipped: {result.get('reason', 'unknown reason')}"
    else:
        message = f"❌ Memory consolidation failed: {result.get('error', 'unknown error')}"

    try:
        await bot.send_message(chat_id=target_user_id, text=message)
        logger.success("Memory consolidation notification sent successfully to user {}", target_user_id)
    except TelegramError as e:
        logger.error("Failed to send memory consolidation notification via Telegram: {}", e)


class MemoryConsolidationTask:
    """Scheduled task that performs weekly memory consolidation."""

    def __init__(self, config: MemoryConsolidationTaskConfig, obsidian_config: "ObsidianConfig", bot: Bot) -> None:
        self.config = config
        self.obsidian_config = obsidian_config
        self.bot = bot
        self._memory_config_dict = self._serialize_memory_config()
        self._obsidian_config_dict = self._serialize_obsidian_config()

    def _serialize_memory_config(self) -> dict[str, Any]:
        """Serialize the memory consolidation config to a pickleable dict."""
        return {
            "enabled": self.config.enabled,
            "weekly_memory_dir": self.config.weekly_memory_dir,
            "persistent_memory_file": self.config.persistent_memory_file,
            "ai_logs_dir": self.config.ai_logs_dir,
            "daily_notes_dir": self.config.daily_notes_dir,
            "summarization_llm_config": self.config.summarization_llm_config.model_dump(),
            "fact_extraction_llm_config": self.config.fact_extraction_llm_config.model_dump(),
            "days_to_process_for_weekly": self.config.days_to_process_for_weekly,
            "weekly_summary_prompt": self.config.weekly_summary_prompt,
            "fact_extraction_prompt": self.config.fact_extraction_prompt,
            "persistent_memory_default_section": self.config.persistent_memory_default_section,
            "persistent_memory_section_routing": self.config.persistent_memory_section_routing,
        }

    def _serialize_obsidian_config(self) -> dict[str, Any]:
        """Serialize the obsidian config to a pickleable dict."""
        return {
            "obsidian_root_dir": str(self.obsidian_config.obsidian_root_dir),
            "daily_notes_dir": str(self.obsidian_config.daily_notes_dir),
            "ai_assistant_memory_logs": str(self.obsidian_config.ai_assistant_memory_logs),
        }

    def register_with_scheduler(self, scheduler: ScheduledTaskService) -> None:
        """Register the memory consolidation task with the scheduler."""
        if not self.config.enabled:
            logger.info("Memory consolidation task is disabled, not registering with scheduler")
            return

        logger.info("Registering memory consolidation task with schedule: {}", self.config.schedule_time)

        # Create a partial callback function with the required parameters
        callback_fn = partial(
            _memory_consolidation_callback,
            target_user_id=self.config.target_user_id,
            bot_token=self.bot.token,
        )

        scheduler.add_job_to_background_executor(
            cron_expression=self.config.schedule_time,
            target_fn=_perform_memory_consolidation,
            target_args=(
                self._memory_config_dict,
                self._obsidian_config_dict,
            ),
            callback_fn=callback_fn,
            job_id="memory_consolidation",
            display_name="Memory Consolidation",
            description="Weekly summary and persistent memory extraction from Obsidian logs.",
            metadata={
                "target_user_id": self.config.target_user_id,
                "weekly_memory_dir": self.config.weekly_memory_dir,
            },
        )

        logger.info("Memory consolidation task registered successfully")


def create_memory_consolidation_task(
    config: MemoryConsolidationTaskConfig, obsidian_config: "ObsidianConfig", bot: Bot
) -> MemoryConsolidationTask:
    """Factory function to create a configured memory consolidation task."""
    return MemoryConsolidationTask(config, obsidian_config, bot)
