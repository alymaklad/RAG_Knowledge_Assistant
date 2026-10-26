"""Qdrant access. One collection holds every course; `course_id` is a tenant payload index.

Each point carries a named dense vector (BGE-m3, 1024-d, cosine) and a named sparse vector
(BGE-m3 lexical weights), so hybrid retrieval needs no separate keyword index.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.services.embeddings.client import SparseVec

DENSE = "dense"
SPARSE = "sparse"


@dataclass(slots=True)
class ChunkPoint:
    id: uuid.UUID
    dense: list[float]
    sparse: SparseVec | None
    payload: dict[str, Any]


@dataclass(slots=True)
class Hit:
    id: str
    score: float
    payload: dict[str, Any]


def make_client(url: str, api_key: str | None) -> AsyncQdrantClient:
    if url == ":memory:":
        return AsyncQdrantClient(location=":memory:")
    return AsyncQdrantClient(url=url, api_key=api_key or None)


class VectorStore:
    def __init__(self, client: AsyncQdrantClient, collection: str, dim: int) -> None:
        self.client = client
        self.collection = collection
        self.dim = dim

    async def ensure_collection(self) -> None:
        if await self.client.collection_exists(self.collection):
            return
        await self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                DENSE: models.VectorParams(size=self.dim, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={SPARSE: models.SparseVectorParams()},
        )
        await self.client.create_payload_index(
            self.collection,
            field_name="course_id",
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD, is_tenant=True
            ),
        )
        await self.client.create_payload_index(
            self.collection, field_name="document_id", field_schema=models.PayloadSchemaType.KEYWORD
        )

    async def upsert(self, points: list[ChunkPoint], batch_size: int = 128) -> None:
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            await self.client.upsert(
                collection_name=self.collection,
                points=[
                    models.PointStruct(
                        id=str(p.id),
                        vector=self._vectors(p),
                        payload=p.payload,
                    )
                    for p in batch
                ],
                wait=True,
            )

    @staticmethod
    def _vectors(p: ChunkPoint) -> dict[str, Any]:
        vectors: dict[str, Any] = {DENSE: p.dense}
        if p.sparse is not None and p.sparse.indices:
            vectors[SPARSE] = models.SparseVector(indices=p.sparse.indices, values=p.sparse.values)
        return vectors

    async def delete_document(self, document_id: uuid.UUID) -> None:
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=str(document_id))
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def delete_course(self, course_id: uuid.UUID) -> None:
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(filter=self._course_filter(course_id)),
            wait=True,
        )

    @staticmethod
    def _course_filter(
        course_id: uuid.UUID, document_ids: list[uuid.UUID] | None = None
    ) -> models.Filter:
        must: list[models.Condition] = [
            models.FieldCondition(key="course_id", match=models.MatchValue(value=str(course_id)))
        ]
        if document_ids:
            must.append(
                models.FieldCondition(
                    key="document_id", match=models.MatchAny(any=[str(d) for d in document_ids])
                )
            )
        return models.Filter(must=must)

    async def search(
        self,
        *,
        course_id: uuid.UUID,
        dense: list[float],
        sparse: SparseVec | None,
        limit: int,
        hybrid: bool,
        document_ids: list[uuid.UUID] | None = None,
        score_threshold: float | None = None,
    ) -> list[Hit]:
        """Search one course. The course filter is always applied: callers cannot omit it."""
        flt = self._course_filter(course_id, document_ids)
        if hybrid and sparse is not None and sparse.indices:
            result = await self.client.query_points(
                collection_name=self.collection,
                prefetch=[
                    models.Prefetch(query=dense, using=DENSE, limit=limit, filter=flt),
                    models.Prefetch(
                        query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                        using=SPARSE,
                        limit=limit,
                        filter=flt,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=True,
            )
        else:
            result = await self.client.query_points(
                collection_name=self.collection,
                query=dense,
                using=DENSE,
                query_filter=flt,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )
        return [Hit(id=str(p.id), score=p.score, payload=p.payload or {}) for p in result.points]

    async def neighbors(
        self, course_id: uuid.UUID, document_id: str, lo: int, hi: int
    ) -> list[Hit]:
        """Chunks lo..hi (by chunk_index) of one document, in order."""
        flt = self._course_filter(course_id)
        flt.must.extend(  # type: ignore[union-attr]
            [
                models.FieldCondition(
                    key="document_id", match=models.MatchValue(value=document_id)
                ),
                models.FieldCondition(key="chunk_index", range=models.Range(gte=lo, lte=hi)),
            ]
        )
        points, _ = await self.client.scroll(
            self.collection, scroll_filter=flt, limit=hi - lo + 1, with_payload=True
        )
        hits = [Hit(id=str(p.id), score=0.0, payload=p.payload or {}) for p in points]
        return sorted(hits, key=lambda h: int(h.payload.get("chunk_index", 0)))

    async def count(self, course_id: uuid.UUID | None = None) -> int:
        flt = self._course_filter(course_id) if course_id else None
        res = await self.client.count(self.collection, count_filter=flt, exact=True)
        return res.count
