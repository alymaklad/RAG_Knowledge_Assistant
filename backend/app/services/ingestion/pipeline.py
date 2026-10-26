"""Indexing pipeline: extract -> clean/chunk -> embed (BGE-m3 dense + sparse) -> Qdrant + Postgres.

Idempotent: re-running on a document replaces its previous chunks and points.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chunk, DocStatus, Document
from app.services.container import Services
from app.services.ingestion.chunk import chunk_pages
from app.services.ingestion.extract import extract
from app.services.vectorstore.qdrant import ChunkPoint

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


async def _set_status(db: AsyncSession, doc: Document, status: DocStatus) -> None:
    doc.status = status
    await db.commit()


async def process_document(
    document_id: uuid.UUID,
    services: Services,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    settings = services.settings
    async with sessionmaker() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            logger.warning("Document %s vanished before processing", document_id)
            return
        try:
            await _set_status(db, doc, DocStatus.EXTRACTING)
            extracted = await asyncio.to_thread(extract, doc.file_path, doc.mime_type or "")
            doc.page_count = extracted.page_count
            if not extracted.pages:
                raise IngestionError(
                    "No extractable text found (the file may be scanned images; OCR isn't "
                    "supported yet)"
                )

            await _set_status(db, doc, DocStatus.CHUNKING)
            chunks = await asyncio.to_thread(
                chunk_pages,
                extracted.pages,
                chunk_size=settings.chunk_size_tokens,
                chunk_overlap=settings.chunk_overlap_tokens,
                tokenizer_name=settings.chunk_tokenizer,
            )
            if not chunks:
                raise IngestionError("Document produced no chunks after cleaning")

            await _set_status(db, doc, DocStatus.EMBEDDING)
            embeddings = await services.embedder.embed([c.embedding_text for c in chunks])

            # Replace any previous indexing of this document.
            await services.vectors.delete_document(doc.id)
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))

            rows: list[Chunk] = []
            points: list[ChunkPoint] = []
            for i, c in enumerate(chunks):
                chunk_id = uuid.uuid4()
                rows.append(
                    Chunk(
                        id=chunk_id,
                        document_id=doc.id,
                        chunk_index=c.chunk_index,
                        text=c.text,
                        page_num=c.page_num,
                        token_count=c.token_count,
                        section_header=c.section_header,
                        metadata_={"skipped_pages": extracted.skipped_pages} if i == 0 else {},
                    )
                )
                points.append(
                    ChunkPoint(
                        id=chunk_id,
                        dense=embeddings.dense[i],
                        sparse=embeddings.sparse[i] if embeddings.sparse else None,
                        payload={
                            "course_id": str(doc.course_id),
                            "document_id": str(doc.id),
                            "document_name": doc.filename,
                            "chunk_index": c.chunk_index,
                            "page_num": c.page_num,
                            "section_header": c.section_header,
                            "token_count": c.token_count,
                            "text": c.text,
                        },
                    )
                )
            db.add_all(rows)
            await db.flush()
            await services.vectors.upsert(points)

            doc.chunk_count = len(rows)
            doc.status = DocStatus.INDEXED
            doc.error_message = None
            doc.processed_at = datetime.now(UTC)
            await db.commit()
            logger.info("Indexed %s: %d pages, %d chunks", doc.filename, doc.page_count, len(rows))
        except Exception as exc:
            logger.exception("Indexing failed for document %s", document_id)
            await db.rollback()
            doc = await db.get(Document, document_id)
            if doc is not None:
                doc.status = DocStatus.FAILED
                doc.error_message = (
                    str(exc) if isinstance(exc, IngestionError) else f"{type(exc).__name__}: {exc}"
                )[:2000]
                await db.commit()
            # Leave no half-written vectors behind.
            await services.vectors.delete_document(document_id)
