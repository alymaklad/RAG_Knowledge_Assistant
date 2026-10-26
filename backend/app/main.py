import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, chat, courses, documents, health
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
        app.state.arq = None
        if settings.ingest_mode == "queue":
            app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        app.state.redis = app.state.arq
        try:
            await app.state.services.vectors.ensure_collection()
        except Exception:  # Qdrant may still be starting; /ready reports it
            logger.exception("Could not ensure Qdrant collection at startup")
        yield
        await app.state.services.aclose()
        if app.state.arq is not None:
            await app.state.arq.aclose()
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

    for module in (health, auth, courses, documents, chat):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
