"""Query-time retrieval for one course.

question (+ optional LLM paraphrases)
  -> BGE-m3 dense (+ sparse) query vectors
  -> Qdrant search per query (dense, or dense+sparse fused with RRF)
  -> fuse the per-query lists (RRF)
  -> cross-encoder re-rank (bge-reranker-v2-m3) of the top candidates
  -> top N
"""

import logging
import uuid
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import Settings
from app.services.container import Services
from app.services.retrieval.query import expand_queries
from app.services.vectorstore.qdrant import Hit

logger = logging.getLogger(__name__)

RRF_K = 60


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

    @property
    def rerank_text(self) -> str:
        return f"{self.section_header}\n{self.text}" if self.section_header else self.text

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


def _from_hit(h: Hit) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=h.id,
        document_id=str(h.payload.get("document_id", "")),
        document_name=str(h.payload.get("document_name", "Unknown")),
        page_num=h.payload.get("page_num"),
        section_header=h.payload.get("section_header"),
        chunk_index=int(h.payload.get("chunk_index", 0)),
        text=str(h.payload.get("text", "")),
        score=h.score,
    )


def rrf_fuse(rankings: list[list[RetrievedChunk]]) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion across several ranked lists (one per query phrasing)."""
    if len(rankings) == 1:
        return rankings[0]
    scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            chunks.setdefault(chunk.chunk_id, chunk)
    ordered = sorted(scores, key=scores.__getitem__, reverse=True)
    return [replace(chunks[cid], score=scores[cid]) for cid in ordered]


async def rerank(
    services: Services, query: str, chunks: list[RetrievedChunk]
) -> list[RetrievedChunk] | None:
    """Cross-encoder re-ranking. Returns None if the reranker is unavailable (caller keeps the
    retrieval order), so a still-downloading model degrades quality, not availability."""
    if not chunks:
        return chunks
    try:
        scores = await services.embedder.rerank(query, [c.rerank_text for c in chunks])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reranker unavailable (%s); using retrieval order", exc)
        return None
    ranked = sorted(zip(chunks, scores, strict=True), key=lambda p: p[1], reverse=True)
    return [replace(c, rerank_score=float(s)) for c, s in ranked]


async def expand_with_neighbors(
    services: Services, course_id: uuid.UUID, chunks: list[RetrievedChunk], n: int
) -> list[RetrievedChunk]:
    """Match on small chunks, answer from the surrounding passage: replace each chunk's text
    with itself plus up to `n` neighbouring chunks of the same document, without repeats."""
    seen: set[str] = set()
    out: list[RetrievedChunk] = []
    for c in chunks:
        if c.chunk_id in seen:
            continue
        hits = await services.vectors.neighbors(
            course_id, c.document_id, max(0, c.chunk_index - n), c.chunk_index + n
        )
        parts = [h for h in hits if h.id == c.chunk_id or h.id not in seen]
        seen.update(h.id for h in parts)
        text = "\n\n".join(str(h.payload.get("text", "")) for h in parts) or c.text
        out.append(replace(c, text=text))
    return out


async def retrieve(
    services: Services,
    *,
    course_id: uuid.UUID,
    query: str,
    document_ids: list[uuid.UUID] | None = None,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    s = settings or services.settings
    queries = [query]
    if s.multi_query:
        queries += await expand_queries(services.llm, query, s.multi_query_count)

    candidates = s.retrieval_top_k if s.rerank_enabled else s.rerank_top_n
    emb = await services.embedder.embed(queries, sparse=s.hybrid_search)
    rankings: list[list[RetrievedChunk]] = []
    for i in range(len(queries)):
        hits = await services.vectors.search(
            course_id=course_id,
            dense=emb.dense[i],
            sparse=emb.sparse[i] if emb.sparse else None,
            limit=candidates,
            hybrid=s.hybrid_search,
            document_ids=document_ids,
            # Raw cosine thresholds only make sense for plain dense search.
            score_threshold=s.score_threshold
            if not (s.hybrid_search or s.rerank_enabled)
            else None,
        )
        rankings.append([_from_hit(h) for h in hits])
    chunks = rrf_fuse(rankings)

    if s.rerank_enabled:
        reranked = await rerank(services, query, chunks)
        if reranked is not None:
            chunks = reranked
            if s.rerank_threshold is not None:
                chunks = [c for c in chunks if (c.rerank_score or 0.0) >= s.rerank_threshold]
    chunks = chunks[: s.rerank_top_n]
    if s.context_neighbors > 0:
        chunks = await expand_with_neighbors(services, course_id, chunks, s.context_neighbors)
    return chunks
