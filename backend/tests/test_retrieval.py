import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.services.container import Services
from app.services.embeddings.client import HashEmbeddingClient
from app.services.llm.client import FakeLLM
from app.services.retrieval.query import rewrite_standalone
from app.services.retrieval.retriever import RetrievedChunk, retrieve, rrf_fuse
from app.services.vectorstore.qdrant import ChunkPoint, VectorStore

COURSE = uuid.UUID(int=1)
TEXTS = [
    "The Markov blanket of a node consists of its parents, children and co-parents.",
    "Slow start doubles the congestion window every round-trip time.",
    "The Viterbi algorithm replaces the sum with a maximum.",
    "Laplace smoothing adds one pseudo-count to every cell.",
]


class FlakyReranker(HashEmbeddingClient):
    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        raise RuntimeError("503 reranker loading")


class ReverseReranker(HashEmbeddingClient):
    """Scores documents in reverse retrieval order, to prove reranking reorders results."""

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [float(i) for i in range(len(documents))]


async def _services(embedder: Any = None, **overrides: Any) -> Services:
    plain = {"hybrid_search": False, "rerank_enabled": False, "rerank_threshold": None}
    settings = get_settings().model_copy(update={**plain, **overrides})
    embedder = embedder or HashEmbeddingClient(64)
    store = VectorStore(AsyncQdrantClient(location=":memory:"), "t", 64)
    await store.ensure_collection()
    emb = await embedder.embed(TEXTS)
    await store.upsert(
        [
            ChunkPoint(
                id=uuid.uuid4(),
                dense=emb.dense[i],
                sparse=emb.sparse[i],
                payload={"course_id": str(COURSE), "document_id": "d", "text": t},
            )
            for i, t in enumerate(TEXTS)
        ]
    )
    return Services(settings=settings, embedder=embedder, vectors=store, llm=FakeLLM())


def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(cid, "d", "doc", None, None, 0, cid, 0.0)


def test_rrf_rewards_agreement_across_rankings() -> None:
    fused = rrf_fuse([[_chunk("a"), _chunk("b")], [_chunk("b"), _chunk("c")]])
    assert [c.chunk_id for c in fused] == ["b", "a", "c"]


async def test_hybrid_retrieval_finds_exact_terms() -> None:
    services = await _services(hybrid_search=True, rerank_top_n=2)
    chunks = await retrieve(services, course_id=COURSE, query="Viterbi maximum")
    assert chunks[0].text.startswith("The Viterbi algorithm")
    assert len(chunks) == 2


async def test_reranker_reorders_candidates() -> None:
    services = await _services(
        ReverseReranker(64), rerank_enabled=True, retrieval_top_k=4, rerank_top_n=4
    )
    plain = await _services(rerank_enabled=False, rerank_top_n=4)
    before = [c.text for c in await retrieve(plain, course_id=COURSE, query="markov blanket")]
    after = await retrieve(services, course_id=COURSE, query="markov blanket")
    assert [c.text for c in after] == list(reversed(before))
    assert after[0].rerank_score == 3.0


async def test_reranker_failure_falls_back_to_retrieval_order() -> None:
    services = await _services(FlakyReranker(64), rerank_enabled=True, rerank_top_n=2)
    chunks = await retrieve(services, course_id=COURSE, query="markov blanket")
    assert chunks and chunks[0].text.startswith("The Markov blanket")
    assert chunks[0].rerank_score is None


async def test_rerank_threshold_drops_weak_matches() -> None:
    services = await _services(
        ReverseReranker(64), rerank_enabled=True, rerank_top_n=4, rerank_threshold=2.5
    )
    chunks = await retrieve(services, course_id=COURSE, query="markov blanket")
    assert [c.rerank_score for c in chunks] == [3.0]


async def test_rewrite_is_skipped_without_history() -> None:
    llm = FakeLLM()
    assert await rewrite_standalone(llm, [], "What is TCP?") == "What is TCP?"
    assert llm.calls == []


async def test_rewrite_uses_history() -> None:
    llm = FakeLLM()
    llm.text_responders["standalone search queries"] = lambda m: "How does TCP handle loss?"
    history = [
        {"role": "user", "content": "What is TCP?"},
        {"role": "assistant", "content": "A reliable transport protocol."},
    ]
    out = await rewrite_standalone(llm, history, "And how does it handle loss?")
    assert out == "How does TCP handle loss?"
    assert "Follow-up question: And how does it handle loss?" in llm.calls[0][-1]["content"]
