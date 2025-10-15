import importlib
from collections.abc import AsyncIterator
from functools import cached_property
from typing import Any, Optional, Union

from langchain_core.language_models import BaseChatModel, BaseLLM
from langchain_core.messages import AIMessageChunk
from loguru import logger
from pydantic import BaseModel
from typing_extensions import TypeVar


class LLMConfig(BaseModel):
    llm_class_path: str
    llm_kwargs: dict[str, Any]
    stop_words: Optional[list[str]] = None


class LLMServiceException(Exception):
    pass


T = TypeVar("T", bound=BaseModel)


class LLMService:
    def __init__(self, llm_config: LLMConfig) -> None:
        self.llm_config = llm_config

    @cached_property
    def _llm(self) -> Union[BaseLLM, BaseChatModel]:
        try:
            module_name, class_name = self.llm_config.llm_class_path.rsplit(".", 1)
            module = importlib.import_module(module_name)
            llm_class = getattr(module, class_name)
        except AttributeError as e:
            raise LLMServiceException(f"LLM class {self.llm_config.llm_class_path} not found") from e

        if not issubclass(llm_class, BaseLLM) and not issubclass(llm_class, BaseChatModel):
            raise ValueError(f"Class {self.llm_config.llm_class_path} has to be of type BaseChatModel or BaseLLM")
        try:
            return llm_class(**self.llm_config.llm_kwargs)
        except Exception as e:
            raise LLMServiceException(f"Error while creating LLM {llm_class}: {e}") from e

    async def astream_llm(self, prompt: str) -> AsyncIterator[str]:
        logger.debug(f"Prompting in stream mode LLM {self._llm.name} with: {prompt}")

        chunk: AIMessageChunk
        async for chunk in self._llm.astream(input=prompt, stop=self.llm_config.stop_words):
            yield chunk.content

    async def aprompt_llm(self, prompt: str) -> str:
        logger.debug(f"Prompting LLM {self._llm.name} with: {prompt}")
        answer = await self._llm.ainvoke(input=prompt, stop=self.llm_config.stop_words)
        if hasattr(answer, "content"):
            answer = answer.content
        logger.debug(f"LLM answer: {answer}")
        return answer

    def prompt_llm(self, prompt: str) -> str:
        logger.debug(f"Prompting LLM {self._llm.name} with: {prompt}")
        answer = self._llm.invoke(input=prompt, stop=self.llm_config.stop_words)
        if hasattr(answer, "content"):
            answer = answer.content
        logger.debug(f"LLM answer: {answer}")
        return answer

    def prompt_llm_with_structured_output(self, prompt: str, output_type: type[T]) -> T:
        logger.debug(f"Prompting LLM {self._llm.name} with: {prompt} using structured output type {output_type}")
        output = self._llm.with_structured_output(output_type).invoke(prompt, stop=self.llm_config.stop_words)
        logger.debug(f"LLM structured output: {output}")
        return output

    async def aprompt_llm_with_structured_output(self, prompt: str, output_type: type[T]) -> T:
        logger.debug(f"Prompting LLM {self._llm.name} with: {prompt} using structured output type {output_type}")
        output = await self._llm.with_structured_output(output_type).ainvoke(prompt, stop=self.llm_config.stop_words)
        logger.debug(f"LLM structured output: {output}")
        return output
