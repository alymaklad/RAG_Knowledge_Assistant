"""Test setup: real Postgres (a separate `courseai_test` database), in-process Qdrant,
hash embeddings and a fake LLM, so the suite needs no model downloads or API keys."""

import os

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+asyncpg://courseai:courseai@localhost:5433/courseai_test",
        ),
        "QDRANT_URL": ":memory:",
        "EMBEDDER_BACKEND": "hash",
        "LLM_PROVIDER": "fake",
        "INGEST_MODE": "inline",
        "CHUNK_TOKENIZER": "approx",
        "RATE_LIMIT_ENABLED": "false",
        "UPLOAD_DIR": os.path.join(os.path.dirname(__file__), ".uploads"),
    }
)

from collections.abc import AsyncIterator  # noqa: E402

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import create_app  # noqa: E402


async def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", parsed.database
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{parsed.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    get_settings.cache_clear()
    await _ensure_database(get_settings().database_url)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(scope="session")
async def app(database: None) -> AsyncIterator[FastAPI]:
    application = create_app(get_settings())
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
