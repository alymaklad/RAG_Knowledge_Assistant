"""Per-user rate limits (slowapi), stored in Redis so limits hold across API workers.

Keys are the authenticated user id when there is one, otherwise the client IP.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings


def _key(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else f"ip:{get_remote_address(request)}"


def _storage_uri() -> str:
    settings = get_settings()
    return settings.redis_url if settings.ingest_mode == "queue" else "memory://"


limiter = Limiter(
    key_func=_key,
    storage_uri=_storage_uri(),
    enabled=get_settings().rate_limit_enabled,
    headers_enabled=False,
    strategy="moving-window",
)


async def _exceeded(request: Request, exc: Exception) -> JSONResponse:
    detail = getattr(exc, "detail", "")
    return JSONResponse(
        {"detail": f"Too many requests ({detail}). Wait a moment and try again."},
        status_code=429,
    )


def install(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _exceeded)
