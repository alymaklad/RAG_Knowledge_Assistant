"""Query-time retrieval: embed the question, search the course's chunks in Qdrant."""

import uuid
from dataclasses import dataclass
from typing import Any

from app.services.container import Services


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    page_num: int | None
    section_header: str | None
    chunk_index: int
    text: str
    score: float
    rerank_score: float | None = None

    @property
    def display_score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.score

    def as_source(self, index: int, text_limit: int | None = None) -> dict[str, Any]:
        text = self.text if text_limit is None else self.text[:text_limit]
        return {
            "index": index,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page_num": self.page_num,
            "section_header": self.section_header,
            "score": round(self.display_score, 4),
            "text": text,
        }


async def retrieve(
    services: Services,
    *,
    course_id: uuid.UUID,
    query: str,
    document_ids: list[uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    settings = services.settings
    emb = await services.embedder.embed([query], sparse=settings.hybrid_search)
    hits = await services.vectors.search(
        course_id=course_id,
        dense=emb.dense[0],
        sparse=emb.sparse[0] if emb.sparse else None,
        limit=settings.rerank_top_n,
        hybrid=settings.hybrid_search,
        document_ids=document_ids,
        score_threshold=settings.score_threshold,
    )
    return [
        RetrievedChunk(
            chunk_id=h.id,
            document_id=str(h.payload.get("document_id", "")),
            document_name=str(h.payload.get("document_name", "Unknown")),
            page_num=h.payload.get("page_num"),
            section_header=h.payload.get("section_header"),
            chunk_index=int(h.payload.get("chunk_index", 0)),
            text=str(h.payload.get("text", "")),
            score=h.score,
        )
        for h in hits
    ]
