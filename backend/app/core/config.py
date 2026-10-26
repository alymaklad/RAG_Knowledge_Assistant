from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-change-me-in-production-0123456789"


class Settings(BaseSettings):
    """All runtime configuration, read from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False  # one JSON object per line, with request ids (production)

    # Datastores
    database_url: str = "postgresql+asyncpg://courseai:courseai@localhost:5433/courseai"
    qdrant_url: str = "http://localhost:6335"  # ":memory:" runs Qdrant in-process (tests)
    qdrant_api_key: str | None = None
    qdrant_collection: str = "course_chunks"
    redis_url: str = "redis://localhost:6380/0"

    # Embeddings (BGE-m3 served by the embedder service)
    embedder_backend: Literal["http", "hash"] = "http"
    embedder_url: str = "http://localhost:8001"
    embedding_dim: int = 1024
    embed_batch_size: int = 32

    # LLM (any OpenAI-compatible endpoint: OpenAI, Ollama, vLLM)
    llm_provider: Literal["openai", "fake"] = "openai"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_max_tokens: int = 1000
    llm_temperature_qa: float = 0.1
    llm_temperature_creative: float = 0.7
    llm_timeout_seconds: float = 120.0

    # Auth
    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    cookie_secure: bool = False

    # Chunking
    chunk_size_tokens: int = 800
    chunk_overlap_tokens: int = 100
    chunk_tokenizer: str = "BAAI/bge-m3"  # "approx" = ~4 chars/token, no download

    # Retrieval
    retrieval_top_k: int = 20
    rerank_top_n: int = 5
    hybrid_search: bool = True
    rerank_enabled: bool = True
    # Reranker (0-1 sigmoid) score below which passages are dropped. Calibrated on the eval set:
    # lowest answerable top score 0.386, highest unanswerable 0.011 (eval/RESULTS.md).
    rerank_threshold: float | None = 0.1
    score_threshold: float | None = None  # raw cosine; dense-only search without reranking
    multi_query: bool = False
    multi_query_count: int = 3
    query_rewrite: bool = True  # make follow-up questions standalone before retrieval
    # Parent-child style expansion: add this many neighbouring chunks on each side of every
    # retrieved chunk. Off by default: it lifts Hit@1 0.96 -> 1.00 on the eval set but makes the
    # prompt 2-3x longer (eval/RESULTS.md). Worth enabling for long-context models.
    context_neighbors: int = 0
    history_turns: int = 4

    # Uploads / ingestion
    max_upload_mb: int = 50
    upload_dir: str = "uploads"
    ingest_mode: Literal["queue", "inline"] = "queue"

    # HTTP
    cors_origins: list[str] = Field(default_factory=list)

    # Rate limits (per user when signed in, else per IP; slowapi syntax)
    rate_limit_enabled: bool = True
    rate_limit_auth: str = "10/minute"
    rate_limit_chat: str = "20/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_study: str = "10/minute"

    def check_production_safety(self) -> None:
        """Refuse to start in production with development secrets."""
        if self.environment != "production":
            return
        if self.jwt_secret_key == DEV_JWT_SECRET or len(self.jwt_secret_key) < 32:
            raise RuntimeError("Set JWT_SECRET_KEY to a random value of at least 32 characters")
        if not self.cookie_secure:
            raise RuntimeError("Set COOKIE_SECURE=true in production (HTTPS only cookies)")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
