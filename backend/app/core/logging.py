"""Structured (JSON) logging with a request id on every line, and a middleware that sets it."""

import contextvars
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SKIP_ACCESS_LOG = {"/api/health"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key in ("method", "path", "status", "duration_ms", "user_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, json_logs: bool) -> None:
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        )
        handler.addFilter(_RequestIdFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # httpx logs every Qdrant/embedder call at INFO; that drowns out application logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def install_request_logging(app: FastAPI) -> None:
    access = logging.getLogger("courseai.access")

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            if request.url.path not in _SKIP_ACCESS_LOG:
                access.info(
                    "%s %s %s",
                    request.method,
                    request.url.path,
                    status,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - start) * 1000),
                        "user_id": str(getattr(request.state, "user_id", "") or ""),
                    },
                )
            request_id_var.reset(token)
