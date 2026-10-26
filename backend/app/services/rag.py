"""RAG orchestration: retrieve -> build prompt -> stream the grounded answer."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from app.services.container import Services
from app.services.llm.client import Message, Usage
from app.services.llm.prompts import (
    NOT_FOUND_ANSWER,
    SYSTEM_PROMPT,
    build_user_message,
    format_context,
)
from app.services.retrieval.retriever import RetrievedChunk, retrieve


@dataclass(slots=True)
class RagEvent:
    kind: Literal["sources", "token", "usage"]
    sources: list[RetrievedChunk] | None = None
    token: str | None = None
    usage: Usage | None = None


async def stream_answer(
    services: Services,
    *,
    course_id: uuid.UUID,
    question: str,
    history: list[Message],
    document_ids: list[uuid.UUID] | None = None,
) -> AsyncIterator[RagEvent]:
    settings = services.settings
    chunks = await retrieve(
        services, course_id=course_id, query=question, document_ids=document_ids
    )
    yield RagEvent("sources", sources=chunks)

    if not chunks:
        # Nothing relevant indexed: don't spend an LLM call to say so.
        yield RagEvent("token", token=NOT_FOUND_ANSWER)
        return

    context = format_context([c.as_source(i) for i, c in enumerate(chunks, 1)])
    messages: list[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": build_user_message(question, context)})

    async for item in services.llm.stream(
        messages, temperature=settings.llm_temperature_qa, max_tokens=settings.llm_max_tokens
    ):
        if isinstance(item, Usage):
            yield RagEvent("usage", usage=item)
        else:
            yield RagEvent("token", token=item)
