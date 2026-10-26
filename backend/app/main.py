import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, auth, chat, courses, documents, health, study
from app.core import ratelimit
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, install_request_logging
from app.db.session import dispose_engine
from app.services.container import build_services

logger = logging.getLogger("courseai")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.check_production_safety()
    configure_logging(settings.log_level, settings.log_json)

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

    app = FastAPI(
        title="Course AI Assistant API",
        version="1.0.0",
        lifespan=lifespan,
        # Interactive docs only outside production.
        docs_url=None if settings.environment == "production" else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/api/openapi.json",
    )
    app.state.settings = settings
    ratelimit.install(app)
    install_request_logging(app)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    for module in (health, auth, courses, documents, chat, study, analytics):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
