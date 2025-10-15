from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from telegram_bot.service.correlation_engine.models import CorrelationFetchConfig
from telegram_bot.service.llm_service import LLMConfig


class ContextTriggerConfig(BaseModel):
    name: str
    llm_config: LLMConfig
    prompt_template: str
    description: Optional[str] = None
    garmin_lookback_days: int = 3
    obsidian_lookback_days: int = 3
    calendar_lookback_days: int = 1
    calendar_lookahead_days: int = 2
    correlation_fetch: CorrelationFetchConfig = CorrelationFetchConfig(lookback_days=5, max_events=5)
    analysis_prompt: str = """Jesteś inteligentnym analizatorem kontekstu dla osobistego asystenta.

KRYTERIA/TRIGGER (wytyczne specyficzne dla tego wywołania):
{trigger_criteria}

DANE KONTEKSTOWE (notatki, Garmin, kalendarz, przypomnienia):
{context_data}

Instrukcje decyzyjne:
- Oceniaj dowody i cytuj je zwięźle w uzasadnieniu (np. fragment notatki, metryka + czas).
- Uwzględnij świeżość danych Garmina. Jeśli widzisz oznaczenie „STALE” lub ostatnia próbka jest stara (np. >6h), nie opieraj się wyłącznie na Garminie; bazuj na notatkach/kalendarzu albo obniż pewność.
- Jeśli dane są niespójne lub niejednoznaczne, nie aktywuj triggera (should_trigger=false) i wyjaśnij dlaczego.
- Wiadomości mają być zwięzłe, życzliwe, konkretne i po polsku. Sugeruj proste, natychmiastowe działania (np. krótka przerwa, brain dump, propozycja dodania przypomnienia/spotkania), ale nie wykonuj automatyzacji – tylko opisz propozycję.
- Priorytet ustaw wg pilności i wpływu: urgent (pilne), high (ważne), normal (typowe), low (opcjonalne).

Zwróć WYŁĄCZNIE obiekt JSON o dokładnie takiej strukturze:
{
  "should_trigger": boolean,
  "confidence": number między 0.0 i 1.0,
  "reasoning": "krótkie uzasadnienie z odniesieniem do danych",
  "suggested_message": "krótka wiadomość dla użytkownika po polsku lub null",
  "priority": "low" lub "normal" lub "high" lub "urgent"
}

Bądź obiektywny i aktywuj tylko przy wyraźnych przesłankach. Wiadomość ma być praktyczna i wykonalna."""  # noqa: E501


class TriggerPrio(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TriggerAnalysisResult(BaseModel):
    should_trigger: bool = Field(description="Whether the trigger should fire based on the analysis")
    confidence: float = Field(description="Confidence level of the decision (0.0 to 1.0)", ge=0.0, le=1.0)
    reasoning: str = Field(description="Clear explanation of why trigger should or should not fire")
    suggested_message: Optional[str] = Field(
        default=None, description="Message to send to user if trigger fires, or null if no trigger"
    )
    priority: TriggerPrio = Field(description="Priority level of the trigger (low, normal, high, urgent)")
