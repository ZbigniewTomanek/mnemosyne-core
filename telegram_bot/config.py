from pathlib import Path
from typing import Union
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_bot.ai_assistant.agents.ai_assitant_agent import AIAssistantConfig
from telegram_bot.constants import DefaultLLMConfig
from telegram_bot.handlers.commands.logs_command import LogAnalysisConfig
from telegram_bot.scheduled_tasks.memory_consolidation_task import MemoryConsolidationTaskConfig
from telegram_bot.scheduled_tasks.morning_report_task import MorningReportTaskConfig
from telegram_bot.service.calendar_service.calendar_service import CalendarConfig
from telegram_bot.service.context_trigger import ContextTriggerConfig
from telegram_bot.service.correlation_engine.models import (
    ActivityImpactVarianceConfig,
    BioSignalType,
    CorrelationJobConfig,
    CorrelationSourcesConfig,
    MetricThreshold,
    SleepCorrelationConfig,
    WindowConfig,
)
from telegram_bot.service.life_context import LifeContextConfig
from telegram_bot.service.obsidian.obsidian_daily_notes_manager import ObsidianDailyNotesManagerConfig
from telegram_bot.service.obsidian.obsidian_service import ObsidianConfig


class CorrelationMetricConfig(BaseModel):
    enabled: bool = True
    threshold: MetricThreshold = Field(default_factory=MetricThreshold)


class ChromaVectorStoreConfig(BaseModel):
    enabled: bool = True
    refresh_enabled: bool = True
    collection_name: str = "obsidian-notes"
    persist_relative_dir: Path = Path("chroma")
    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_batch_size: int = 64
    chunk_size: int = 800
    chunk_overlap: int = 200
    refresh_cron: str = "0 3 * * *"
    query_top_k: int = 5

    def resolve_persist_path(self, out_dir: Path) -> Path:
        persist_dir = Path(self.persist_relative_dir)
        if persist_dir.is_absolute():
            return persist_dir
        return Path(out_dir) / persist_dir


class CorrelationEngineConfig(BaseModel):
    enabled: bool = True
    cron: str = "0 2 * * *"
    lookback_days: int = 1
    timezone: str | None = None
    window: WindowConfig = Field(default_factory=WindowConfig)
    metrics: dict[BioSignalType, CorrelationMetricConfig] = Field(
        default_factory=lambda: {
            BioSignalType.STRESS: CorrelationMetricConfig(
                threshold=MetricThreshold(min_delta=28.0, min_samples=10, min_confidence=0.95)
            ),
            BioSignalType.BODY_BATTERY: CorrelationMetricConfig(
                threshold=MetricThreshold(min_delta=22.0, min_samples=10, min_confidence=0.95)
            ),
            BioSignalType.HEART_RATE: CorrelationMetricConfig(
                threshold=MetricThreshold(min_delta=13.0, min_samples=10, min_confidence=0.95)
            ),
            BioSignalType.BREATHING_RATE: CorrelationMetricConfig(
                threshold=MetricThreshold(min_delta=5.0, min_samples=10, min_confidence=0.95)
            ),
            BioSignalType.SLEEP: CorrelationMetricConfig(
                threshold=MetricThreshold(min_delta=20.0, min_samples=3, min_confidence=0.9)
            ),
        }
    )
    sources: CorrelationSourcesConfig = Field(default_factory=CorrelationSourcesConfig)
    sleep_analysis: SleepCorrelationConfig = Field(default_factory=SleepCorrelationConfig)
    variance_analysis: ActivityImpactVarianceConfig = Field(default_factory=ActivityImpactVarianceConfig)

    def to_job_config(self) -> CorrelationJobConfig:
        enabled_metrics = {metric: cfg.threshold for metric, cfg in self.metrics.items() if cfg.enabled}
        return CorrelationJobConfig(
            lookback_days=self.lookback_days,
            timezone=self.timezone or "UTC",
            metrics=enabled_metrics,
            windows=self.window.model_copy(deep=True),
            sources=CorrelationSourcesConfig.model_validate(self.sources.model_dump()),
            sleep_analysis=SleepCorrelationConfig.model_validate(self.sleep_analysis.model_dump()),
            variance_analysis=ActivityImpactVarianceConfig.model_validate(self.variance_analysis.model_dump()),
        )


class WhisperSettings(BaseSettings):
    model_size: str
    device: str = "auto"
    device_index: Union[int, list[int]] = 0
    compute_type: str = "default"
    cpu_threads: int = 0
    num_workers: int = 1
    download_root: Path = Path("./.cache/whisper")
    local_files_only: bool = False


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    telegram_bot_api_key: str
    my_telegram_user_id: int
    read_timeout_s: int = 30
    write_timeout_s: int = 30
    out_dir: Path = "./out"
    garmin_token_dir: Path = "./out/garmin_tokens"
    executor_num_async_workers: int = 4
    executor_num_cpu_workers: int = 2
    whisper: WhisperSettings
    ai_assistant: AIAssistantConfig
    life_context: LifeContextConfig = LifeContextConfig()
    morning_report: MorningReportTaskConfig = MorningReportTaskConfig()
    memory_consolidation: MemoryConsolidationTaskConfig = MemoryConsolidationTaskConfig()
    log_analysis: LogAnalysisConfig = LogAnalysisConfig()
    chroma_vector_store: ChromaVectorStoreConfig = Field(default_factory=ChromaVectorStoreConfig)
    obsidian_config: ObsidianConfig = ObsidianConfig()
    obsidian_daily_notes_manager_config: ObsidianDailyNotesManagerConfig = ObsidianDailyNotesManagerConfig()
    calendar_config: CalendarConfig = CalendarConfig(
        excluded_title_patterns=[
            # Add your calendar event patterns to exclude here
            # Example: r"Team Standup", r"1:1 Meeting"
        ]
    )
    correlation_engine: CorrelationEngineConfig = CorrelationEngineConfig()

    # Smart Context Triggers
    context_trigger_task_config: dict[str, ContextTriggerConfig] = {
        "30 8 * * *": ContextTriggerConfig(
            name="Poranny Przegląd Dnia",
            llm_config=DefaultLLMConfig.GEMINI_FLASH,
            description="Ocena gotowości, wykrywanie symptomów choroby oraz dopasowanie planu dnia.",
            prompt_template="""
        Cel: ocenić gotowość do dnia i wykryć symptomy choroby, używając trendów i jakości danych.
        Wytyczne:
        - Porównaj sen i energię (Body Battery) do ostatnich ~3 dni (trendy, nie progi stałe).
        - Uwzględnij świeżość danych Garmina (oznaczenia 'STALE' lub stare próbki). Jeśli dane są nieświeże, oprzyj się głównie na notatkach/kalendarzu i obniż pewność.
        - Przejrzyj dzisiejszą notatkę: liczba zadań/spotkań, sygnały przeciążenia, wzmianki o objawach (np. ból gardła, drapanie w gardle, katar, kaszel, dreszcze, rozbicie, stan podgorączkowy, "chyba mnie bierze").
        - Jeśli są symptomy choroby lub wyraźnie niższa energia przy wymagającym dniu: zaproponuj wsparcie (np. przypomnienie o cynku i NAC dziś rano lub przy pierwszym oknie), oraz zachęć do zawężenia planu (priorytety, przełożenie drobnych rzeczy).
        - Jeśli energia/rutyna wyglądają dobrze i kalendarz jest lekki: zasugeruj, że to dobry moment na ważniejszą rzecz z listy priorytetów.
        - Komunikat zwięzły, wspierający, z konkretną propozycją działania (bez automatyzacji – tylko sugestia).
        """,  # noqa: E501
        ),
        # CRON dla 13:00, codziennie
        "0 13 * * *": ContextTriggerConfig(
            name="Popołudniowy Reset Energii",
            llm_config=DefaultLLMConfig.GEMINI_FLASH,
            description="Analiza wzorców z ostatnich dni w celu rekomendacji spersonalizowanej mikro-przerwy.",
            prompt_template="""
    Cel: Jesteś coachem specjalizującym się w zarządzaniu energią i prewencji wypalenia. Twoim zadaniem jest ocena bieżącego stanu (stres, energia) w kontekście ostatnich dni, aby zaproponować spersonalizowaną i kreatywną przerwę. Twoim priorytetem jest unikanie powtarzalnych, generycznych sugestii.

    <INSTRUKCJE_KROK_PO_KROKU>

    <KROK_1_ANALIZA_OBECNEGO_STANU>
    - Porównaj obecny poziom Body Battery z wartością poranną oraz medianą z ostatnich 3 godzin.
    - Przeanalizuj trend stresu z ostatnich 3 godzin. Czy jest stabilny, rosnący, czy malejący?
    - Przejrzyj dzisiejsze notatki pod kątem słów kluczowych wskazujących na obciążenie: "hyperfocus", "presja", "przeciążenie", "trudności", "irytacja".
    </KROK_1_ANALIZA_OBECNEGO_STANU>

    <KROK_2_ANALIZA_KONTEKSTU_HISTORYCZNEGO>
    - Porównaj dzisiejsze wzorce (stres, spadek energii) z danymi z ostatnich dni.
    - Zidentyfikuj powtarzające się schematy. Np. "Czy wtorki po południu są regularnie stresujące?", "Czy po spotkaniach planistycznych zawsze następuje spadek Body Battery?".
    - Sprawdź, czy podobne sugestie były już ostatnio proponowane, aby uniknąć powtórzeń.
    </KROK_2_ANALIZA_KONTEKSTU_HISTORYCZNEGO>

    <KROK_3_DECYZJA_I_SPERSONALIZOWANA_SUGESTIA>
    - Aktywuj trigger (should_trigger: true) TYLKO jeśli zauważysz negatywny trend (utrzymujący się stres, szybki spadek energii) LUB zidentyfikujesz powtarzający się, negatywny wzorzec z poprzednich dni.
    - Jeśli aktywujesz trigger, wygeneruj JEDNĄ, adekwatną do kontekstu i możliwie nowatorską sugestię.
    - Zasady generowania sugestii:
        - Jeśli stres jest wysoki, zaproponuj aktywność wyciszającą układ nerwowy (np. techniki oddechowe, krótka medytacja, słuchanie uspokajającej muzyki, joga nidra).
        - Jeśli energia jest niska, ale stres umiarkowany, zaproponuj coś aktywizującego (np. krótki spacer, dynamiczne rozciąganie, zmiana otoczenia).
        - Bądź kreatywny. Zamiast "idź na spacer", możesz zasugerować "10-minutowy spacer z celem znalezienia trzech ciekawych detali w otoczeniu" albo "5-minutowa sesja rozciągania bioder po długim siedzeniu".
    - Uzasadnij swój wybór, odnosząc się do zaobserwowanego wzorca.
    - Przykład: "Zauważyłem, że podobnie jak wczoraj, po południu Twój poziom stresu rośnie. Aby nie powtarzać wczorajszej sugestii, może dziś spróbujesz 5-minutowej sesji 'box breathing', aby szybko obniżyć napięcie przed kolejnym zadaniem?"
    </KROK_3_DECYZJA_I_SPERSONALIZOWANA_SUGESTIA>

    </INSTRUKCJE_KROK_PO_KROKU>
    """,  # noqa: E501
        ),
        # CRON dla 19:00, codziennie  "0 19 * * *"
        "0 19 * * *": ContextTriggerConfig(
            name="Wieczorne Wyciszenie",
            llm_config=DefaultLLMConfig.GEMINI_FLASH,
            description="Analiza intensywności dnia i sugestia aktywności regeneracyjnej w "
            "celu wyciszenia układu nerwowego.",
            prompt_template="""
        Cel: Jesteś asystentem specjalizującym się w neurobiologii stresu i regeneracji. Twoim jedynym zadaniem jest ocena, czy dzisiejszy dzień był na tyle intensywny (fizycznie lub mentalnie), że uzasadnia to sugestię konkretnej aktywności pomagającej wyciszyć układ nerwowy. Aktywuj ten trigger TYLKO wtedy, gdy dane wyraźnie wskazują na podwyższony poziom stresu lub obciążenia.

        Zadania, których NIE wykonujesz:
        - NIE podsumowujesz dnia.
        - NIE analizujesz zrealizowanych zadań.
        - NIE planujesz jutra.
        - NIE sugerujesz "brain dumpów" ani innych zadań kognitywnych.

        Wytyczne:

        <KROK_1_ANALIZA_OBCIAZENIA_DNIA>
        - Przeanalizuj dane z Garmina: skup się na trendzie stresu w ciągu dnia, szczególnie w ostatnich 3-4 godzinach. Zwróć uwagę na nagłe skoki lub długo utrzymujący się podwyższony poziom.
        - Sprawdź poziom Body Battery i porównaj jego spadek z typowym przebiegiem.
        - Przejrzyj notatki wyłącznie w poszukiwaniu słów kluczowych wskazujących na wysokie obciążenie, np. "stres", "napięcie", "przebodźcowanie", "trudne spotkanie", "ciężki dzień".
        </KROK_1_ANALIZA_OBCIAZENIA_DNIA>

        <KROK_2_DECYZJA_O_AKTYWACJI>
        - Aktywuj trigger (should_trigger: true) tylko, jeśli co najmniej jeden z poniższych warunków jest spełniony:
          a) Średni poziom stresu w ostatnich 3 godzinach jest wyraźnie podwyższony.
          b) W notatkach znajdują się jednoznaczne sformułowania o stresującym lub intensywnym dniu.
          c) Dzień był wyjątkowo aktywny fizycznie, co może prowadzić do pobudzenia.
        - Jeśli dzień był spokojny lub dane są niejednoznaczne, nie aktywuj triggera.
        </KROK_2_DECYZJA_O_AKTYWACJI>

        <KROK_3_SUGESTIA_AKTYWNOSCI_REGENERACYJNEJ>
        - Jeśli trigger jest aktywowany, zaproponuj JEDNĄ, prostą i konkretną czynność mającą na celu obniżenie pobudzenia.
        - Wybierz sugestię dopasowaną do kontekstu:
          - Jeśli dzień był obciążający mentalnie, ale mało aktywny fizycznie: zasugeruj krótki spacer.
          - Jeśli dzień był intensywny fizycznie: zasugeruj sesję rozciągania lub jogi nidry.
          - W przypadku ogólnego przebodźcowania: zasugeruj 10-minutową sesję oddechową (np. metoda 4-7-8) lub posłuchanie spokojnej muzyki w ciszy, bez ekranu.
        </KROK_3_SUGESTIA_AKTYWNOSCI_REGENERACYJNEJ>

        <FORMAT_WIADOMOSCI>
        - Komunikat musi być bardzo krótki, empatyczny i konkretny.
        - Bezpośrednio wskaż przyczynę (np. "Dzisiejszy wysoki poziom stresu...") i od razu podaj sugestię.
        - Przykład: "Zauważyłem, że dzisiejszy dzień, zwłaszcza popołudnie, był dość napięty. Aby pomóc układowi nerwowemu przejść w tryb regeneracji, rozważ krótki, 15-minutowy spacer w ciszy."
        </FORMAT_WIADOMOSCI>
        """,  # noqa: E501
        ),
        # CRON dla 21:00, codziennie
        "0 21 * * *": ContextTriggerConfig(
            name="Konsolidacja Dnia",
            llm_config=DefaultLLMConfig.GEMINI_FLASH,
            description=(
                "Pomaga w refleksji nad dniem, domknięciu otwartych pętli i strategicznym przygotowaniu na jutro."
            ),
            prompt_template="""
    Cel: Jesteś coachem i strategiem, który pomaga mi domknąć dzień i świadomie przygotować się na kolejny. Twoim zadaniem jest dostarczenie zwięzłego podsumowania, które pomoże mi w wieczornej refleksji, zidentyfikuje niedomknięte sprawy i wygeneruje konkretne, praktyczne alerty dotyczące jutrzejszego planu.

    <INSTRUKCJE_KROK_PO_KROKU>

    <KROK_1_ANALIZA_WPLYWU_DNIA>
    - Przejrzyj notatki i dane z Garmina. Zidentyfikuj jedną kluczową obserwację dotyczącą dzisiejszego dnia. Co miało największy wpływ na moją energię, samopoczucie lub produktywność?
    - Porównaj przebieg dnia z porannymi hipotezami lub planami. Gdzie wystąpiła największa rozbieżność? Sformułuj to jako zwięzły wniosek do mojej refleksji.
    </KROK_1_ANALIZA_WPLYWU_DNIA>

    <KROK_2_IDENTYFIKACJA_OTWARTYCH_PETLI>
    - Sprawdź listę przypomnień. Wymień zwięźle te, które są zaległe lub nadchodzące w ciągu najbliższych 24 godzin, aby nic mi nie umknęło.
    </KROK_2_IDENTYFIKACJA_OTWARTYCH_PETLI>

    <KROK_3_STRATEGICZNE_ALERTY_NA_JUTRO>
    - Przeanalizuj kalendarz na następny dzień pod kątem następujących warunków i wygeneruj odpowiednie alerty:
      a) **Wczesny Start:** Jeśli pierwsze wydarzenie jest przed godziną 9:00, zasugeruj potrzebę wcześniejszego wstania. (Przykład: "Uwaga, jutro zaczynasz dzień od spotkania o 8:30. Pamiętaj, by nastawić budzik odpowiednio wcześniej.")
      b) **Wydarzenie Poza Domem/Biurem:** Jeśli w kalendarzu jest wydarzenie z lokalizacją inną niż domyślna, przypomnij o konieczności zaplanowania czasu na dojazd. (Przykład: "Jutrzejsza wizyta u stomatologa o 14:00 jest w innej lokalizacji. Nie zapomnij uwzględnić czasu na dotarcie na miejsce.")
      c) **Specjalna Okazja:** Jeśli tytuł wydarzenia zawiera słowa takie jak "urodziny", "rocznica", przypomnij o tym. (Przykład: "Pamiętaj, jutro są urodziny Twojego ojca. Dobry moment, by rano wysłać życzenia.")
      d) **Wysoka Intensywność:** Jeśli kalendarz na jutro jest zapełniony spotkaniami (np. 4 lub więcej), a przerwy między nimi są krótkie, zasugeruj proaktywnie zaplanowanie chwili na regenerację. (Przykład: "Twój jutrzejszy kalendarz wygląda bardzo intensywnie. Może warto już teraz zarezerwować 20 minut na przerwę w ciągu dnia, aby złapać oddech?")
    - Jeśli żaden z powyższych warunków nie jest spełniony, podaj ogólną, pozytywną zachętę na nadchodzący dzień.
    </KROK_3_STRATEGICZNE_ALERTY_NA_JUTRO>

    <KROK_4_FORMULOWANIE_WIADOMOSCI>
    - Złóż elementy z kroków 1-3 w jedną, spójną i krótką wiadomość.
    - Struktura wiadomości: (1) Kluczowa obserwacja z dzisiaj. (2) Przypomnienia do zaadresowania. (3) Konkretne alerty i wskazówki na jutro.
    - Ton ma być wspierający i coachingowy.
    </KROK_4_FORMULOWANIE_WIADOMOSCI>

    </INSTRUKCJE_KROK_PO_KROKU>
    """,  # noqa: E501
        ),
    }

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.calendar_config.timezone)
