import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.core.deps import AppServices, CurrentUser, DbSession, Membership, get_membership
from app.db.models import ChatMessage, ChatSession, MsgRole
from app.db.session import get_sessionmaker
from app.schemas.common import ChatRequest, MessageOut, SessionOut, SessionUpdate
from app.services.llm.client import Message, Usage
from app.services.rag import stream_answer
from app.services.retrieval.retriever import RetrievedChunk

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

SOURCE_TEXT_LIMIT = 1200  # stored with each assistant message for the citation viewer


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _own_session(db: DbSession, session_id: uuid.UUID, user_id: uuid.UUID) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat session not found")
    return session


async def load_history(db: DbSession, session_id: uuid.UUID, turns: int) -> list[Message]:
    rows = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(turns * 2)
    )
    return [{"role": m.role.value, "content": m.content} for m in reversed(list(rows))]


@router.get("/courses/{course_id}/sessions", response_model=list[SessionOut])
async def list_sessions(
    course_id: uuid.UUID, member: Membership, db: DbSession, q: str | None = None
) -> list[ChatSession]:
    query = select(ChatSession).where(
        ChatSession.course_id == course_id, ChatSession.user_id == member.user_id
    )
    if q:
        query = query.where(func.lower(ChatSession.title).contains(q.lower()))
    rows = await db.scalars(query.order_by(ChatSession.updated_at.desc()).limit(100))
    return list(rows)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[ChatMessage]:
    await _own_session(db, session_id, user.id)
    rows = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    return list(rows)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: uuid.UUID, body: SessionUpdate, user: CurrentUser, db: DbSession
) -> ChatSession:
    session = await _own_session(db, session_id, user.id)
    session.title = body.title
    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    session = await _own_session(db, session_id, user.id)
    await db.delete(session)
    await db.commit()


async def _save_assistant(
    session_id: uuid.UUID, content: str, sources: list[RetrievedChunk], usage: Usage | None
) -> uuid.UUID:
    async with get_sessionmaker()() as db:
        msg = ChatMessage(
            session_id=session_id,
            role=MsgRole.ASSISTANT,
            content=content,
            source_chunks=[c.as_source(i, SOURCE_TEXT_LIMIT) for i, c in enumerate(sources, 1)],
            tokens_used=usage.total_tokens if usage else None,
        )
        db.add(msg)
        session = await db.get(ChatSession, session_id)
        if session is not None:
            session.updated_at = func.now()
        await db.commit()
        return msg.id


@router.post("/chat")
async def chat(
    body: ChatRequest, user: CurrentUser, db: DbSession, services: AppServices
) -> StreamingResponse:
    """Stream a grounded answer as Server-Sent Events.

    Events, in order: `session`, `sources`, `token`*, then `done` (or `error`).
    """
    await get_membership(body.course_id, user, db)

    if body.session_id is not None:
        session = await _own_session(db, body.session_id, user.id)
        if session.course_id != body.course_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Session belongs to another course")
    else:
        title = " ".join(body.message.split())[:80]
        session = ChatSession(user_id=user.id, course_id=body.course_id, title=title)
        db.add(session)
        await db.flush()

    history = await load_history(db, session.id, services.settings.history_turns)
    # The user's message is saved before streaming, so it survives a dropped connection.
    db.add(ChatMessage(session_id=session.id, role=MsgRole.USER, content=body.message))
    await db.commit()
    session_out = SessionOut.model_validate(session).model_dump(mode="json")

    async def events() -> AsyncIterator[str]:
        parts: list[str] = []
        sources: list[RetrievedChunk] = []
        usage: Usage | None = None
        saved = False

        async def save(suffix: str = "") -> uuid.UUID | None:
            nonlocal saved
            if saved:
                return None
            saved = True
            content = "".join(parts).strip() + suffix
            if not content:
                return None
            return await _save_assistant(session.id, content, sources, usage)

        try:
            yield sse("session", session_out)
            async for ev in stream_answer(
                services,
                course_id=body.course_id,
                question=body.message,
                history=history,
                document_ids=body.document_ids,
            ):
                if ev.kind == "sources" and ev.sources is not None:
                    sources = ev.sources
                    yield sse(
                        "sources",
                        [c.as_source(i, SOURCE_TEXT_LIMIT) for i, c in enumerate(sources, 1)],
                    )
                elif ev.kind == "token" and ev.token:
                    parts.append(ev.token)
                    yield sse("token", {"t": ev.token})
                elif ev.kind == "usage":
                    usage = ev.usage
            message_id = await save()
            yield sse(
                "done",
                {"message_id": message_id, "tokens_used": usage.total_tokens if usage else None},
            )
        except asyncio.CancelledError:
            # Client went away mid-answer: keep what was generated.
            await asyncio.shield(save("\n\n*(response interrupted)*"))
            raise
        except Exception:
            logger.exception("Chat generation failed")
            await save("\n\n*(response failed)*")
            yield sse("error", {"message": "The assistant failed to generate an answer."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
