from langchain_google_genai import HarmBlockThreshold, HarmCategory

from telegram_bot.service.llm_service import LLMConfig

MAX_TOKENS = 32_000  # Maximum number of tokens for LLMs in this bot
DEFAULT_TIMEZONE = "Europe/Warsaw"


class DefaultLLMConfig:
    GPT_O_4_MINI = LLMConfig(
        llm_class_path="langchain_openai.ChatOpenAI", llm_kwargs={"model_name": "gpt-5", "max_tokens": MAX_TOKENS}
    )
    GEMINI_PRO = LLMConfig(
        llm_class_path="langchain_google_genai.ChatGoogleGenerativeAI",
        llm_kwargs={
            "model": "gemini-2.5-pro",
            "max_tokens": MAX_TOKENS,
            "safety_settings": {
                HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DEROGATORY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_TOXICITY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_VIOLENCE: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_MEDICAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY: HarmBlockThreshold.BLOCK_NONE,
            },
        },
    )
    GEMINI_FLASH = LLMConfig(
        llm_class_path="langchain_google_genai.ChatGoogleGenerativeAI",
        llm_kwargs={
            "model": "gemini-2.5-flash",
            "max_tokens": MAX_TOKENS,
            "safety_settings": {
                HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DEROGATORY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_TOXICITY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_VIOLENCE: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_MEDICAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY: HarmBlockThreshold.BLOCK_NONE,
            },
        },
    )
    CLAUDE_SONNET_4 = LLMConfig(
        llm_class_path="langchain_anthropic.ChatAnthropic",
        llm_kwargs={"model_name": "claude-sonnet-4-20250514", "max_tokens": MAX_TOKENS},
    )
