"""Phase-11 API: login / current user / logout.

Password auth against ``user.hashed_password`` -> a signed access token. Refresh
tokens, rotation, MFA, and server-side revocation land in Phase 12.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from apps.api.deps import Principal, current_user, db_session, resolve_user
from database.repositories import UserRepository
from security.auth import create_access_token, verify_password
from security.config import get_settings

router = APIRouter(tags=["auth"], prefix="/auth")

SessionDep = Annotated[Session, Depends(db_session)]
UserDep = Annotated[Principal, Depends(current_user)]


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: dict


class MeOut(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    role: str


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, session: SessionDep) -> TokenOut:
    user = UserRepository(session).get_by_email(str(body.email))
    if (
        user is None
        or not user.is_active
        or not verify_password(body.password, user.hashed_password)
    ):
        raise HTTPException(status_code=401, detail="invalid email or password")

    ttl = get_settings().access_token_ttl_seconds
    token = create_access_token(user_id=user.id, role=user.role, ttl_seconds=ttl)
    return TokenOut(
        access_token=token,
        expires_in=ttl,
        user={
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "display_name": user.display_name,
        },
    )


@router.get("/me", response_model=MeOut)
def me(session: SessionDep, principal: UserDep) -> MeOut:
    user = resolve_user(session, principal)
    return MeOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


@router.post("/logout")
def logout() -> dict:
    # Stateless tokens: the client discards it. Server-side revocation is Phase 12.
    return {"ok": True}
