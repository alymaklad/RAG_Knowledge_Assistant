"""Long-lived service clients, built once per process (API app or worker)."""

from dataclasses import dataclass

from app.core.config import Settings
from app.services.embeddings.client import (
    EmbeddingClient,
    HashEmbeddingClient,
    HttpEmbeddingClient,
)
from app.services.llm.client import FakeLLM, LLMClient, OpenAICompatibleLLM
from app.services.vectorstore.qdrant import VectorStore, make_client


@dataclass
class Services:
    settings: Settings
    embedder: EmbeddingClient
    vectors: VectorStore
    llm: LLMClient

    async def aclose(self) -> None:
        await self.embedder.aclose()
        await self.vectors.client.close()
        await self.llm.aclose()


def build_services(settings: Settings) -> Services:
    embedder: EmbeddingClient
    if settings.embedder_backend == "hash":
        embedder = HashEmbeddingClient(settings.embedding_dim)
    else:
        embedder = HttpEmbeddingClient(settings.embedder_url, settings.embed_batch_size)
    vectors = VectorStore(
        make_client(settings.qdrant_url, settings.qdrant_api_key),
        settings.qdrant_collection,
        settings.embedding_dim,
    )
    llm: LLMClient
    if settings.llm_provider == "fake":
        llm = FakeLLM()
    else:
        llm = OpenAICompatibleLLM(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            settings.llm_timeout_seconds,
        )
    return Services(settings=settings, embedder=embedder, vectors=vectors, llm=llm)
