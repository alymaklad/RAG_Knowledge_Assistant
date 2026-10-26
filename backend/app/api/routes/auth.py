from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.deps import AppSettings, CurrentUser, DbSession
from app.core.ratelimit import limiter
from app.core.security import (
    REFRESH_COOKIE,
    InvalidToken,
    clear_auth_cookies,
    create_token,
    decode_token,
    hash_password,
    set_auth_cookies,
    verify_password,
)
from app.db.models import User
from app.schemas.common import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Compared against when the email is unknown, so login timing doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("timing-equalizer")


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().rate_limit_auth)
async def register(
    request: Request, body: RegisterIn, response: Response, db: DbSession, settings: AppSettings
) -> TokenOut:
    email = body.email.lower()
    if await db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    set_auth_cookies(response, settings, user.id)
    return TokenOut(
        access_token=create_token(settings, user.id, "access"), user=UserOut.model_validate(user)
    )


@router.post("/login", response_model=TokenOut)
@limiter.limit(lambda: get_settings().rate_limit_auth)
async def login(
    request: Request, body: LoginIn, response: Response, db: DbSession, settings: AppSettings
) -> TokenOut:
    user = await db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    set_auth_cookies(response, settings, user.id)
    return TokenOut(
        access_token=create_token(settings, user.id, "access"), user=UserOut.model_validate(user)
    )


@router.post("/refresh", response_model=UserOut)
async def refresh(
    request: Request, response: Response, db: DbSession, settings: AppSettings
) -> UserOut:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")
    try:
        user_id = decode_token(settings, token, "refresh")
    except InvalidToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    set_auth_cookies(response, settings, user.id)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> Response:
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
