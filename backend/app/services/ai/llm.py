"""Provider-agnostic LLM client.

Talks to any OpenAI-compatible Chat Completions API, so switching between Groq, Gemini,
Ollama or OpenAI is a configuration change (LLM_BASE_URL / LLM_MODEL / LLM_API_KEY).
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.core.config import settings


class LLMNotConfigured(Exception):
    """No API key / endpoint is configured for the LLM provider."""


class LLMError(Exception):
    """The LLM provider failed or returned something unusable."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> LLMResponse: ...


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Parse a JSON object from a model reply, tolerating ```json fences."""
    if not text:
        raise LLMError("Empty response from model")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("Model did not return a JSON object")
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError("Model returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LLMError("Model did not return a JSON object")
    return value


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float, timeout: float):
        # Local servers such as Ollama ignore the key but the SDK requires a value.
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=timeout, max_retries=1)
        self._model = model
        self._temperature = temperature

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature if temperature is None else temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except (APIError, APITimeoutError) as exc:
            raise LLMError(f"LLM provider error: {type(exc).__name__}") from exc

        message = response.choices[0].message
        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        return LLMResponse(content=message.content, tool_calls=tool_calls)


def _is_local_endpoint(base_url: str) -> bool:
    return any(host in base_url for host in ("localhost", "127.0.0.1", "host.docker.internal", "ollama"))


@lru_cache
def _default_llm() -> OpenAICompatibleLLM:
    if not settings.llm_api_key and not _is_local_endpoint(settings.llm_base_url):
        raise LLMNotConfigured("LLM_API_KEY is not set")
    return OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
    )


def get_llm_client() -> LLMClient:
    """FastAPI dependency. Tests override it with a fake client."""
    return _default_llm()
