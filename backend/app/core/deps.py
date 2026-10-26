import secrets
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    InvalidToken,
    decode_token,
)
from app.db.models import CourseMember, MemberRole, User
from app.db.session import get_db
from app.services.container import Services

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]


AppServices = Annotated[Services, Depends(get_services)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, {"WWW-Authenticate": "Bearer"})


async def get_current_user(request: Request, db: DbSession, settings: AppSettings) -> User:
    """Authenticate via `Authorization: Bearer` or the httpOnly access cookie.

    Cookie-authenticated unsafe requests must also send the CSRF cookie value in X-CSRF-Token.
    """
    token: str | None = None
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    else:
        token = request.cookies.get(ACCESS_COOKIE)
        if token and request.method not in SAFE_METHODS:
            cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
            header_csrf = request.headers.get(CSRF_HEADER, "")
            if not cookie_csrf or not secrets.compare_digest(cookie_csrf, header_csrf):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    if not token:
        raise _unauthorized("Not authenticated")
    try:
        user_id = decode_token(settings, token, "access")
    except InvalidToken as exc:
        raise _unauthorized(str(exc)) from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_membership(course_id: uuid.UUID, user: CurrentUser, db: DbSession) -> CourseMember:
    """Every course-scoped route goes through this: no membership, no access.

    Returns 404 rather than 403 so course ids can't be probed.
    """
    member = await db.scalar(
        select(CourseMember).where(
            CourseMember.course_id == course_id, CourseMember.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return member


Membership = Annotated[CourseMember, Depends(get_membership)]


async def require_instructor(member: Membership) -> CourseMember:
    if member.role not in (MemberRole.INSTRUCTOR, MemberRole.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Instructor role required")
    return member


InstructorMembership = Annotated[CourseMember, Depends(require_instructor)]
