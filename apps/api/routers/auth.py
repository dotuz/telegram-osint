"""Phase-11/12 API: login / refresh / current user / logout.

Login issues a short-lived signed access token plus a rotating refresh token.
The refresh token is delivered as an ``HttpOnly; Secure; SameSite=Strict`` cookie
(scoped to ``/api/v1/auth``) **and** in the body for non-browser clients.
Presenting a revoked refresh token nukes the whole token family for that user.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, resolve_user
from apps.api.security import login_rate_limit
from database.repositories import (
    RefreshTokenRepository,
    RefreshTokenReuseError,
    UserRepository,
)
from security.auth import create_access_token, verify_password
from security.config import get_settings

router = APIRouter(tags=["auth"], prefix="/auth")

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]

_REFRESH_COOKIE = "toi_refresh"
_COOKIE_PATH = "/api/v1/auth"


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    refresh_token: str | None = None
    user: dict | None = None


class MeOut(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    role: str


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        _REFRESH_COOKIE,
        raw,
        max_age=get_settings().refresh_token_ttl_seconds,
        path=_COOKIE_PATH,
        httponly=True,
        secure=get_settings().is_production,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(_REFRESH_COOKIE, path=_COOKIE_PATH)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(login_rate_limit)])
def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> TokenOut:
    user = UserRepository(session).get_by_email(str(body.email))
    if (
        user is None
        or not user.is_active
        or not verify_password(body.password, user.hashed_password)
    ):
        raise HTTPException(status_code=401, detail="invalid email or password")

    ttl = get_settings().access_token_ttl_seconds
    access = create_access_token(user_id=user.id, role=user.role, ttl_seconds=ttl)
    refresh = RefreshTokenRepository(session).issue(
        user,
        user_agent=request.headers.get("user-agent"),
        ip_metadata=(request.client.host if request.client else None),
    )
    _set_refresh_cookie(response, refresh)
    return TokenOut(
        access_token=access,
        expires_in=ttl,
        refresh_token=refresh,
        user={
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "display_name": user.display_name,
        },
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    body: RefreshIn | None = None,
    toi_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenOut:
    raw = (body.refresh_token if body else None) or toi_refresh
    if not raw:
        raise HTTPException(status_code=401, detail="no refresh token")
    try:
        new_raw, user = RefreshTokenRepository(session).rotate(
            raw,
            user_agent=request.headers.get("user-agent"),
            ip_metadata=(request.client.host if request.client else None),
        )
    except RefreshTokenReuseError as exc:
        # Persist the family-wide revocation before the error unwinds the request
        # (db_session rolls back on exception).
        session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    ttl = get_settings().access_token_ttl_seconds
    access = create_access_token(user_id=user.id, role=user.role, ttl_seconds=ttl)
    _set_refresh_cookie(response, new_raw)
    return TokenOut(access_token=access, expires_in=ttl, refresh_token=new_raw)


@router.get("/me", response_model=MeOut)
def me(session: SessionDep, principal: UserDep) -> MeOut:
    user = resolve_user(session, principal)
    return MeOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


@router.post("/logout")
def logout(
    response: Response,
    session: SessionDep,
    body: RefreshIn | None = None,
    toi_refresh: Annotated[str | None, Cookie()] = None,
) -> dict:
    raw = (body.refresh_token if body else None) or toi_refresh
    revoked = RefreshTokenRepository(session).revoke(raw) if raw else False
    _clear_refresh_cookie(response)
    return {"ok": True, "revoked": revoked}
