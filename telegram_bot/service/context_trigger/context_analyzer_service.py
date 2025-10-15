from __future__ import annotations

from loguru import logger

from telegram_bot.service.context_trigger.models import ContextTriggerConfig, TriggerAnalysisResult
from telegram_bot.service.llm_service import LLMService


class ContextAnalyzerService:
    """LLM-focused analyzer that turns context data into a TriggerAnalysisResult."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def analyze(self, config: ContextTriggerConfig, context_data: str) -> TriggerAnalysisResult:
        """Analyze context with the configured prompt and return structured output."""
        analysis_prompt = config.analysis_prompt
        analysis_prompt = analysis_prompt.replace("{trigger_criteria}", config.prompt_template)
        analysis_prompt = analysis_prompt.replace("{context_data}", context_data)

        response = await self.llm_service.aprompt_llm_with_structured_output(
            analysis_prompt, output_type=TriggerAnalysisResult
        )
        logger.debug(f"LLM Trigger Analysis Response: {response}")
        return response
