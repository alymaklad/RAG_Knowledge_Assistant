import uuid

import anyio
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import AppServices, DbSession, InstructorMembership, Membership
from app.core.ratelimit import limiter
from app.db.models import Chunk, DocStatus, Document
from app.db.session import get_sessionmaker
from app.schemas.common import DocumentOut
from app.services import storage
from app.services.ingestion.pipeline import process_document
from app.services.ingestion.validate import InvalidUpload, validate_upload

router = APIRouter(prefix="/courses/{course_id}/documents", tags=["documents"])


async def _schedule(
    request: Request, background: BackgroundTasks, services: AppServices, doc_id: uuid.UUID
) -> None:
    if services.settings.ingest_mode == "queue":
        await request.app.state.arq.enqueue_job("ingest_document", str(doc_id))
    else:
        background.add_task(process_document, doc_id, services, get_sessionmaker())


async def _get_doc(db: DbSession, course_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None or doc.course_id != course_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("", response_model=list[DocumentOut])
async def list_documents(course_id: uuid.UUID, member: Membership, db: DbSession) -> list[Document]:
    rows = await db.scalars(
        select(Document).where(Document.course_id == course_id).order_by(Document.created_at.desc())
    )
    return list(rows)


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: get_settings().rate_limit_upload)
async def upload_document(
    course_id: uuid.UUID,
    file: UploadFile,
    request: Request,
    background: BackgroundTasks,
    member: InstructorMembership,
    db: DbSession,
    services: AppServices,
) -> Document:
    settings = services.settings
    data = await file.read(settings.max_upload_bytes + 1)
    filename = (file.filename or "upload").strip()[:500]
    try:
        checked = validate_upload(filename, data, settings.max_upload_bytes)
    except InvalidUpload as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    doc_id = uuid.uuid4()
    path = storage.save(settings, course_id, doc_id, checked.extension, data)
    doc = Document(
        id=doc_id,
        course_id=course_id,
        filename=filename,
        file_path=path,
        file_size=len(data),
        mime_type=checked.mime_type,
        status=DocStatus.UPLOADED,
        uploaded_by=member.user_id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    await _schedule(request, background, services, doc.id)
    return doc


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    course_id: uuid.UUID, doc_id: uuid.UUID, member: Membership, db: DbSession
) -> Document:
    return await _get_doc(db, course_id, doc_id)


@router.get("/{doc_id}/file")
async def get_document_file(
    course_id: uuid.UUID, doc_id: uuid.UUID, member: Membership, db: DbSession
) -> FileResponse:
    """The original upload, served inline so PDFs open in the browser viewer (#page=N works)."""
    doc = await _get_doc(db, course_id, doc_id)
    if not await anyio.Path(doc.file_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File is no longer stored")
    return FileResponse(
        doc.file_path,
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.filename,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.post("/{doc_id}/reprocess", response_model=DocumentOut, status_code=202)
async def reprocess_document(
    course_id: uuid.UUID,
    doc_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    member: InstructorMembership,
    db: DbSession,
    services: AppServices,
) -> Document:
    doc = await _get_doc(db, course_id, doc_id)
    doc.status = DocStatus.UPLOADED
    doc.error_message = None
    await db.commit()
    await db.refresh(doc)
    await _schedule(request, background, services, doc.id)
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    course_id: uuid.UUID,
    doc_id: uuid.UUID,
    member: InstructorMembership,
    db: DbSession,
    services: AppServices,
) -> None:
    doc = await _get_doc(db, course_id, doc_id)
    await services.vectors.delete_document(doc.id)
    path = doc.file_path
    await db.delete(doc)
    await db.commit()
    storage.delete(path)


@router.get("/{doc_id}/chunks")
async def list_chunks(
    course_id: uuid.UUID,
    doc_id: uuid.UUID,
    member: Membership,
    db: DbSession,
    page: int | None = None,
) -> list[dict[str, object]]:
    """Chunks of one document (used by the source viewer when a citation is opened)."""
    await _get_doc(db, course_id, doc_id)
    query = select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
    if page is not None:
        query = query.where(Chunk.page_num == page)
    rows = await db.scalars(query.limit(200))
    return [
        {
            "id": str(c.id),
            "chunk_index": c.chunk_index,
            "page_num": c.page_num,
            "section_header": c.section_header,
            "token_count": c.token_count,
            "text": c.text,
        }
        for c in rows
    ]
