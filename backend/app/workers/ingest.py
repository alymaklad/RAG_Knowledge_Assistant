"""ARQ worker: runs the indexing pipeline off the request path.

Start with: arq app.workers.ingest.WorkerSettings
"""

import logging
import uuid
from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.services.container import build_services
from app.services.ingestion.pipeline import process_document

logger = logging.getLogger(__name__)


async def ingest_document(ctx: dict[str, Any], document_id: str) -> None:
    await process_document(uuid.UUID(document_id), ctx["services"], get_sessionmaker())


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    ctx["services"] = build_services(settings)
    await ctx["services"].vectors.ensure_collection()


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["services"].aclose()
    await dispose_engine()


class WorkerSettings:
    functions = [ingest_document]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 3600  # large textbooks on CPU embeddings take a while
    max_jobs = 2
    keep_result = 3600
