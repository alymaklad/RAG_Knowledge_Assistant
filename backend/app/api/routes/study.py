import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import AppServices, CurrentUser, DbSession, Membership
from app.core.ratelimit import limiter
from app.db.models import Document, DocumentSummary, StudyKind, StudySet
from app.schemas.common import ORMModel
from app.services import study
from app.services.pdf_export import quiz_pdf

router = APIRouter(tags=["study"])


class StudySetIn(BaseModel):
    kind: Literal["quiz", "flashcards"]
    count: int = Field(default=8, ge=3, le=20)
    document_id: uuid.UUID | None = None
    topic: str | None = Field(default=None, max_length=300)


class StudySetOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    document_id: uuid.UUID | None
    kind: StudyKind
    title: str
    topic: str | None
    items: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    created_at: datetime


class SummaryOut(ORMModel):
    document_id: uuid.UUID
    content: str
    sources: list[dict[str, Any]]
    created_at: datetime


async def _own_set(db: DbSession, set_id: uuid.UUID, user_id: uuid.UUID) -> StudySet:
    row = await db.get(StudySet, set_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Study set not found")
    return row


@router.get("/courses/{course_id}/study-sets", response_model=list[StudySetOut])
async def list_study_sets(
    course_id: uuid.UUID, member: Membership, db: DbSession
) -> list[StudySet]:
    rows = await db.scalars(
        select(StudySet)
        .where(StudySet.course_id == course_id, StudySet.user_id == member.user_id)
        .order_by(StudySet.created_at.desc())
        .limit(100)
    )
    return list(rows)


@router.post(
    "/courses/{course_id}/study-sets",
    response_model=StudySetOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(lambda: get_settings().rate_limit_study)
async def create_study_set(
    request: Request,
    course_id: uuid.UUID,
    body: StudySetIn,
    member: Membership,
    db: DbSession,
    services: AppServices,
) -> StudySet:
    topic = body.topic.strip() if body.topic else None
    try:
        material = await study.select_material(
            services, db, course_id=course_id, document_id=body.document_id, topic=topic
        )
        if body.kind == "quiz":
            quiz = await study.make_quiz(services, material, body.count)
            items = [q.model_dump() for q in quiz.questions]
        else:
            cards = await study.make_flashcards(services, material, body.count)
            items = [c.model_dump() for c in cards.flashcards]
    except study.StudyGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    if body.document_id is not None:
        doc = await db.get(Document, body.document_id)
        subject = doc.filename.rsplit(".", 1)[0] if doc else "Document"
    else:
        subject = topic or "Topic"
    label = "Quiz" if body.kind == "quiz" else "Flashcards"
    row = StudySet(
        course_id=course_id,
        user_id=member.user_id,
        document_id=body.document_id,
        kind=StudyKind(body.kind),
        title=f"{label}: {subject}"[:500],
        topic=topic,
        items=items,
        sources=material.sources,
        model=services.llm.model,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/study-sets/{set_id}", response_model=StudySetOut)
async def get_study_set(set_id: uuid.UUID, user: CurrentUser, db: DbSession) -> StudySet:
    return await _own_set(db, set_id, user.id)


@router.delete("/study-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_study_set(set_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    row = await _own_set(db, set_id, user.id)
    await db.delete(row)
    await db.commit()


@router.get("/study-sets/{set_id}/pdf")
async def export_study_set_pdf(
    set_id: uuid.UUID, user: CurrentUser, db: DbSession, answers: bool = True
) -> Response:
    row = await _own_set(db, set_id, user.id)
    if row.kind != StudyKind.QUIZ:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only quizzes can be exported")
    pdf = quiz_pdf(row.title, row.items, row.sources, include_answers=answers)
    filename = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in row.title)[:80]
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


async def _doc_in_course(db: DbSession, course_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None or doc.course_id != course_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("/courses/{course_id}/documents/{doc_id}/summary", response_model=SummaryOut | None)
async def get_summary(
    course_id: uuid.UUID, doc_id: uuid.UUID, member: Membership, db: DbSession
) -> DocumentSummary | None:
    await _doc_in_course(db, course_id, doc_id)
    return await db.get(DocumentSummary, doc_id)


@router.post("/courses/{course_id}/documents/{doc_id}/summary", response_model=SummaryOut)
@limiter.limit(lambda: get_settings().rate_limit_study)
async def create_summary(
    request: Request,
    course_id: uuid.UUID,
    doc_id: uuid.UUID,
    member: Membership,
    db: DbSession,
    services: AppServices,
) -> DocumentSummary:
    """Summaries are shared by everyone in the course, so they're cached per document."""
    await _doc_in_course(db, course_id, doc_id)
    try:
        material = await study.select_material(
            services, db, course_id=course_id, document_id=doc_id, topic=None
        )
        content = await study.make_summary(services, material)
    except study.StudyGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    row = await db.get(DocumentSummary, doc_id)
    if row is None:
        row = DocumentSummary(document_id=doc_id, content=content)
        db.add(row)
    row.content = content
    row.sources = material.sources
    row.created_at = datetime.now(UTC)
    row.model = services.llm.model
    await db.commit()
    await db.refresh(row)
    return row
