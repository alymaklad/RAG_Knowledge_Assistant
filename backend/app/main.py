import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.routes import health
from app.core.config import Settings, get_settings
from app.db.session import dispose_engine
from app.services.container import build_services

logger = logging.getLogger("courseai")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = build_services(settings)
        app.state.redis = (
            Redis.from_url(settings.redis_url) if settings.ingest_mode == "queue" else None
        )
        try:
            await app.state.services.vectors.ensure_collection()
        except Exception:  # Qdrant may still be starting; /ready reports it
            logger.exception("Could not ensure Qdrant collection at startup")
        yield
        await app.state.services.aclose()
        if app.state.redis is not None:
            await app.state.redis.aclose()
        await dispose_engine()

    app = FastAPI(title="Course AI Assistant API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
