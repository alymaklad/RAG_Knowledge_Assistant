from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import get_sessionmaker

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: every dependency the API needs is reachable."""
    services = request.app.state.services
    checks: dict[str, Any] = {}

    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report any failure
        checks["postgres"] = f"error: {exc.__class__.__name__}"

    try:
        await services.vectors.client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["qdrant"] = f"error: {exc.__class__.__name__}"

    try:
        info = await services.embedder.health()
        checks["embedder"] = "ok" if info.get("status") == "ok" else f"error: {info}"
    except Exception as exc:  # noqa: BLE001
        checks["embedder"] = f"error: {exc.__class__.__name__}"

    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {exc.__class__.__name__}"

    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks}, 200 if ok else 503
    )
