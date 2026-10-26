import uuid

from qdrant_client import AsyncQdrantClient

from app.services.embeddings.client import HashEmbeddingClient, hash_dense
from app.services.vectorstore.qdrant import ChunkPoint, VectorStore


async def _store() -> VectorStore:
    store = VectorStore(AsyncQdrantClient(location=":memory:"), "test_chunks", 64)
    await store.ensure_collection()
    return store


async def _index(store: VectorStore, course: uuid.UUID, doc: uuid.UUID, texts: list[str]) -> None:
    emb = await HashEmbeddingClient(store.dim).embed(texts)
    await store.upsert(
        [
            ChunkPoint(
                id=uuid.uuid4(),
                dense=emb.dense[i],
                sparse=emb.sparse[i],
                payload={"course_id": str(course), "document_id": str(doc), "text": t},
            )
            for i, t in enumerate(texts)
        ]
    )


def test_hash_dense_is_normalized_and_deterministic() -> None:
    a = hash_dense("TCP three-way handshake", 1024)
    assert len(a) == 1024
    assert abs(sum(v * v for v in a) - 1.0) < 1e-6
    assert a == hash_dense("TCP three-way handshake", 1024)


async def test_search_is_scoped_to_course() -> None:
    store = await _store()
    course_a, course_b = uuid.uuid4(), uuid.uuid4()
    await _index(store, course_a, uuid.uuid4(), ["markov blanket of a node", "bayes rule"])
    await _index(store, course_b, uuid.uuid4(), ["markov blanket secret notes"])

    emb = await HashEmbeddingClient(64).embed(["markov blanket"])
    for hybrid in (False, True):
        hits = await store.search(
            course_id=course_a,
            dense=emb.dense[0],
            sparse=emb.sparse[0],
            limit=10,
            hybrid=hybrid,
        )
        assert hits, f"hybrid={hybrid}"
        assert {h.payload["course_id"] for h in hits} == {str(course_a)}
        assert hits[0].payload["text"] == "markov blanket of a node"


async def test_delete_document_removes_its_points() -> None:
    store = await _store()
    course, doc_keep, doc_drop = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _index(store, course, doc_keep, ["keep me"])
    await _index(store, course, doc_drop, ["drop me", "drop me too"])
    assert await store.count(course) == 3
    await store.delete_document(doc_drop)
    assert await store.count(course) == 1
