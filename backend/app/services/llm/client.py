"""LLM access through any OpenAI-compatible endpoint (OpenAI, Ollama, vLLM, ...).

The provider is pure configuration: LLM_BASE_URL + LLM_MODEL + LLM_API_KEY. `FakeLLM` is a
deterministic stand-in for tests and offline development.
"""

import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

Message = dict[str, str]


@dataclass(slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class Completion:
    text: str
    usage: Usage | None


class LLMClient(Protocol):
    model: str

    def stream(
        self, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str | Usage]:
        """Yields text deltas, then (if the provider reports it) one `Usage`."""
        ...

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> Completion: ...

    async def aclose(self) -> None: ...


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "unused", timeout=timeout)

    async def stream(
        self, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str | Usage]:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=cast("list[ChatCompletionMessageParam]", messages),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if chunk.usage is not None:
                yield Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> Completion:
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=cast("list[ChatCompletionMessageParam]", messages),
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        usage = (
            Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
            if response.usage
            else None
        )
        return Completion(text=response.choices[0].message.content or "", usage=usage)

    async def aclose(self) -> None:
        await self._client.close()


_SOURCE_RE = re.compile(r"\[Source (\d+)\][^\n]*\n(.+?)(?=\n---\n|\n</context>|\Z)", re.S)


class FakeLLM:
    """Answers by quoting the first retrieved source, citing it. Deterministic, no network.

    `json_responders` maps a marker string (found in the system prompt) to a function that
    builds a JSON response, so structured-output features can be tested end to end.
    """

    model = "fake"

    def __init__(self) -> None:
        self.json_responders: dict[str, Callable[[list[Message]], dict[str, Any]]] = {}
        self.calls: list[list[Message]] = []

    def _answer(self, messages: list[Message]) -> str:
        content = messages[-1]["content"]
        sources = _SOURCE_RE.findall(content)
        if not sources:
            return (
                "I could not find enough information about this in the uploaded course materials."
            )
        num, text = sources[0]
        words = " ".join(text.split()[:60])
        return f"According to the course materials, {words} [Source {num}]."

    async def stream(
        self, messages: list[Message], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[str | Usage]:
        self.calls.append(messages)
        answer = self._answer(messages)
        for word in answer.split(" "):
            yield word + " "
        yield Usage(
            prompt_tokens=sum(len(m["content"]) // 4 for m in messages),
            completion_tokens=len(answer) // 4,
        )

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> Completion:
        self.calls.append(messages)
        if json_mode:
            system = messages[0]["content"]
            for marker, responder in self.json_responders.items():
                if marker in system:
                    return Completion(json.dumps(responder(messages)), None)
            return Completion("{}", None)
        return Completion(self._answer(messages), None)

    async def aclose(self) -> None:
        return None
