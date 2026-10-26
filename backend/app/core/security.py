import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import bcrypt
import jwt
from fastapi import Response

from app.core.config import Settings

TokenType = Literal["access", "refresh"]

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(settings: Settings, user_id: uuid.UUID, token_type: TokenType) -> str:
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class InvalidToken(Exception):
    pass


def decode_token(settings: Settings, token: str, expected_type: TokenType) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise InvalidToken("Wrong token type")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidToken("Invalid subject") from exc


def set_auth_cookies(response: Response, settings: Settings, user_id: uuid.UUID) -> None:
    """Access + refresh tokens in httpOnly cookies; a readable CSRF token for double-submit."""
    common = {"secure": settings.cookie_secure, "samesite": "lax"}
    response.set_cookie(
        ACCESS_COOKIE,
        create_token(settings, user_id, "access"),
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        path="/api",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(settings, user_id, "refresh"),
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        path="/api/auth",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(24),
        max_age=settings.refresh_token_days * 86400,
        httponly=False,
        path="/",
        **common,  # type: ignore[arg-type]
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/api")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")
