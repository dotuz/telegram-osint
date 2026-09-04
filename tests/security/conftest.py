"""Shared fixtures for the security suite."""

from __future__ import annotations

import pytest


@pytest.fixture
def secure_client(settings):
    """A TestClient with two real password users (admin + analyst)."""
    from fastapi.testclient import TestClient

    import database.models  # noqa: F401
    from apps.api.main import create_app
    from database.base import Base
    from database.repositories import UserRepository
    from database.session import get_engine, session_scope
    from database.types import Role

    Base.metadata.create_all(get_engine())
    with session_scope() as s:
        UserRepository(s).create(
            email="admin@sec.example.com", role=Role.ADMIN, password="adminpass-123"
        )
        UserRepository(s).create(email="user-a@sec.example.com", password="user-a-pass-123")
        UserRepository(s).create(email="user-b@sec.example.com", password="user-b-pass-123")
        s.commit()

    app = create_app(settings)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(get_engine())


def token(client, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}
