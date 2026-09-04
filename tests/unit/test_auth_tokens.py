import time

import pytest

from security.auth import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.unit


def test_password_hash_roundtrip():
    h = hash_password("s3cret!")
    assert h.startswith("scrypt$")
    assert verify_password("s3cret!", h)
    assert not verify_password("wrong", h)
    assert not verify_password("s3cret!", None)
    assert not verify_password("x", "not-a-hash")


def test_password_hashes_are_salted():
    assert hash_password("a") != hash_password("a")


def test_token_roundtrip():
    tok = create_access_token(user_id="u1", role="ADMIN", ttl_seconds=60)
    claims = decode_access_token(tok)
    assert claims["sub"] == "u1"
    assert claims["role"] == "ADMIN"


def test_expired_token_rejected():
    tok = create_access_token(user_id="u1", role="ANALYST", ttl_seconds=-1)
    with pytest.raises(TokenError, match="expired"):
        decode_access_token(tok)


def test_tampered_token_rejected():
    tok = create_access_token(user_id="u1", role="ANALYST", ttl_seconds=60)
    head, payload, sig = tok.split(".")
    forged = f"{head}.{payload}x.{sig}"
    with pytest.raises(TokenError):
        decode_access_token(forged)


def test_malformed_token_rejected():
    with pytest.raises(TokenError, match="malformed"):
        decode_access_token("nope")


def test_token_carries_iat_and_exp():
    now = int(time.time())
    claims = decode_access_token(create_access_token(user_id="u", role="ANALYST", ttl_seconds=30))
    assert now - 2 <= claims["iat"] <= now + 2
    assert claims["exp"] - claims["iat"] == 30
