from datetime import datetime
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from telegram_bot.constants import DefaultLLMConfig
from telegram_bot.service.llm_service import LLMConfig, LLMService
from telegram_bot.service.obsidian.obsidian_service import ObsidianService


class ObsidianDailyNotesManagerConfig(BaseModel):
    managing_llm_config: LLMConfig = DefaultLLMConfig.GEMINI_FLASH
    note_transcription_and_tagging_prompt: str = """<task>
Przetwórz notatkę użytkownika do jego dziennej notatki w Obsidian. Popraw tekst jeśli potrzeba (literówki, czytelność), zachowując oryginalny sens i osobisty styl. Wygeneruj trafne, kontekstowe tagi.
</task>

<context>
Treść notatki może pochodzić z rozpoznawania mowy, co może skutkować błędnym rozpoznaniem słów, szczególnie:
- Nazw własnych (osób, firm, projektów)
- Terminów technicznych i branżowych
- Angielskich słów w polskim tekście
- Homofonów (słów brzmiących podobnie)
</context>

<instrukcje>
1. Lekko edytuj notatkę dla czytelności, zachowując głos i intencję użytkownika. Nie używaj formalnego języka, zachowaj osobisty styl, pozostawiając oryginalne brzmienie i przekleństwa.
2. Jeśli wykryjesz prawdopodobne błędy rozpoznawania mowy, popraw je na bardziej sensowne słowa, zachowując oryginał w nawiasach, np.: "projekt Phoenix (feniks)" lub "API (apaj)"
3. Wygeneruj 2-5 trafnych tagów, które pomogą organizować i odnajdywać tę notatkę
4. Tagi powinny być konkretne, nie ogólne (np. #ProjektAlfa zamiast #praca)
5. Używaj formatu CamelCase dla tagów (np. #RefleksjaOsobista, #NotatkiZeSpotkania)
6. Rozważ kategorie: #Zadanie, #Pomysł, #Spotkanie, #Refleksja, #Obserwacja, #Nauka, #Zdrowie, #Finanse
7. Jeśli notatka wspomina konkretne projekty, osoby lub koncepcje, stwórz odpowiednie tagi
8. Zachowaj polskie znaki diakrytyczne w tagach, jeśli są częścią nazwy własnej
</instrukcje>

<note>
{note_content}
</note>

<output_format>
Zwróć czystą, dobrze sformatowaną notatkę z trafnymi tagami. Tagi powinny być znaczące i pomagać w przyszłym wyszukiwaniu. Jeśli poprawiłeś błędy rozpoznawania mowy, zachowaj oryginalne brzmienie w nawiasach.
</output_format>"""  # noqa: E501

    reflection_prompt: str = """<task>
Przeanalizuj interakcję między użytkownikiem a jego asystentem AI, aby stworzyć przemyślaną refleksję do dziennika pamięci AI. Skoncentruj się na zrozumieniu wzorców, potrzeb użytkownika i potencjalnych spostrzeżeń.
</task>

<kontekst>
<notatka_dodana_do_notatki_dziennej>
{note_content}
</notatka_dodana_do_notatki_dziennej>

<current_daily_note_content>
{daily_note}
</current_daily_note_content>
</context>

<instructions>
Sporządź refleksję, która:
1. Określa wyraźny cel lub intencję użytkownika
2. Wyodrębnia kluczowe tematy i podmioty
3. Ostrożnie wnioskuje o stanie emocjonalnym (używaj niepewnych sformułowań, takich jak „wydaje się”, „wygląda na to”, „sugeruje”)
4. Dostarcza użytkownikowi praktycznych wskazówek dotyczących samoświadomości
5. Zwraca uwagę na wszelkie wzorce z poprzednich interakcji (jeśli wynikają one z codziennych notatek)
6. Sugeruje konkretne kolejne kroki zarówno dla użytkownika, jak i sztucznej inteligencji
7. Jest naprawdę pomocna dla samooceny i rozwoju użytkownika
</instructions>

<guidelines>
- Bądź obserwacyjny, a nie nakazowy
- Skup się na wzorcach i powiązaniach
- Dostarczaj konkretnych, praktycznych wskazówek
- Używaj języka ostrożnego w przypadku wniosków dotyczących emocji
- Weź pod uwagę szerszy kontekst dnia użytkownika
</guidelines>"""  # noqa: E501


class TaggedNote(BaseModel):
    note_content: str = Field(description="The processed note content, lightly edited for clarity if needed")
    tags: list[str] = Field(
        description="List of relevant tags in format #TagName",
    )


class AIAssistantReflection(BaseModel):
    """AI's reflection on the interaction for memory and user self-awareness"""

    observed_user_goal: str = Field(description="What the user appeared to want to achieve with this note/interaction")

    key_themes_entities: list[str] = Field(
        description="Main topics, concepts, people, or projects mentioned",
    )

    inferred_emotional_state: Optional[str] = Field(
        description="Carefully inferred emotional state using tentative language (seems, appears, suggests)",
    )

    key_insight_for_user: str = Field(
        description="The single most important insight, question, or thought from this interaction for user reflection"
    )

    potential_patterns: Optional[str] = Field(
        description="Any patterns or connections with other notes/activities visible in the daily note", default=None
    )

    suggested_user_action: Optional[str] = Field(
        description="Concrete action or consideration for the user based on this interaction"
    )

    ai_learning_note: str = Field(description="What the AI learned about user preferences or how to better assist")

    reflection_tags: list[str] = Field(
        description="Tags for the AI log entry with _ai suffix",
    )


class ObsidianDailyNotesManager:
    def __init__(self, obsidian_service: ObsidianService, manager_config: ObsidianDailyNotesManagerConfig) -> None:
        self.obsidian_service = obsidian_service
        self.manager_config = manager_config
        self.managing_llm = LLMService(self.manager_config.managing_llm_config)

    async def log_daily_note(self, note_content: str) -> str:
        """
                 Saves the user's note to their daily note in Obsidian with automatic tagging and AI reflection.

        This feature is the main tool for recording the user's thoughts, observations, tasks, and ideas.
        It automatically processes text (corrects speech recognition errors), generates relevant tags,
                and creates AI reflection for better self-awareness.

                Args:
                    note_content (str): The content of the note to be saved. It can be:
                        - A personal thought or reflection
                        - A task to be done
                        - An observation or insight
                        - An idea for a project
                        - Information to remember
                        - An event from the day

                Returns:
                    str: Formatted note that has been saved (with tags and timestamp)

                    Examples of use:
                        - note_content=“meeting with Anna postponed to Thursday 4:00 p.m.”
                        - note_content="idea for a new feature - add push notifications”
                        - note_content=“today I feel motivated to work on the Phoenix project”
        - note_content=“buy milk, bread, and butter after work”

        Action:
        1. Creates a daily note if it does not exist
        2. Processes text using LLM (corrects errors, adds tags)
                        3. Saves to the “📖 Miscellaneous Thoughts” section with a timestamp
                        4. Generates AI reflection on the interaction
        5. Saves the reflection to the AI log for pattern analysis

        Note:
        - DO NOT use this feature for user questions or commands
        - Use ONLY when the user explicitly wants to take notes
        - The feature will automatically add 2-5 relevant tags
        """
        logger.debug(f"Logging daily note with content: {note_content}")

        now = datetime.now()
        daily_note_path = self.obsidian_service.get_daily_note_path(now)
        if not daily_note_path.exists():
            logger.warning(f"Daily note file does not exist: {daily_note_path}. Creating a new one.")
            daily_note_path.parent.mkdir(parents=True, exist_ok=True)
            await self.obsidian_service.safe_write_file(
                daily_note_path, f"# {now.strftime('%Y-%m-%d')}\n\n## 📖 Myśli przeróżne\n\n"
            )

        # Process note with tagging
        prompt = self.manager_config.note_transcription_and_tagging_prompt.format(note_content=note_content)
        tagged_note: TaggedNote = await self.managing_llm.aprompt_llm_with_structured_output(
            prompt, output_type=TaggedNote
        )

        # Append to daily note
        tags_str = " ".join(tagged_note.tags)
        formatted_note = f"""\n\n{now.strftime('%H:%M')}\n{tagged_note.note_content} {tags_str}\n"""
        await self.obsidian_service.safe_append_file(daily_note_path, formatted_note)

        # Read current daily note for context
        daily_note_content = await self.obsidian_service.safe_read_file(daily_note_path)

        # Generate reflection
        reflection_prompt = self.manager_config.reflection_prompt.format(
            note_content=f"{tagged_note.note_content} {tags_str}", daily_note=daily_note_content
        )
        reflection: AIAssistantReflection = await self.managing_llm.aprompt_llm_with_structured_output(
            reflection_prompt, output_type=AIAssistantReflection
        )

        # Log to AI memory
        ai_log_path = self.obsidian_service.get_ai_log_path(now)
        if not ai_log_path.exists():
            logger.warning(f"AI log file does not exist: {ai_log_path}. Creating a new one.")
            ai_log_path.parent.mkdir(parents=True, exist_ok=True)
            await self.obsidian_service.safe_write_file(
                ai_log_path, f"# AI Assistant Log - {now.strftime('%Y-%m-%d')}\n\n"
            )

        # Format AI log entry
        reflection_tags_str = " ".join(reflection.reflection_tags)
        ai_log_entry = f"""\n\n
**Interaction at {now.strftime('%Y-%m-%d %H:%M:%S')}**

**User Note:**
{note_content}


**AI REFLECTION (For User Self-Awareness):**
* **Observed User Goal/Intention:** {reflection.observed_user_goal}
* **Key Themes/Keywords/Entities:** {', '.join(reflection.key_themes_entities)}
* **Inferred Emotional State:** {reflection.inferred_emotional_state or "No clear emotional indicators observed"}
* **Key Insight for User:** {reflection.key_insight_for_user}
* **Potential Patterns or Connections:** {reflection.potential_patterns or "No immediate patterns identified"}
* **Suggested Action for User:** {reflection.suggested_user_action or "Continue current approach"}
* **AI Learning Note:** {reflection.ai_learning_note}

**REFLECTION TAGS:** {reflection_tags_str}
"""

        # Append to AI log
        await self.obsidian_service.safe_append_file(ai_log_path, ai_log_entry)

        logger.info("Successfully logged note to daily note and AI reflection log")
        return formatted_note
