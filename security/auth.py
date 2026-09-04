"""Password hashing and stateless access tokens.

Standard-library only (no argon2/bcrypt/jose dependency):
  * passwords -> ``scrypt`` with a random salt, encoded ``scrypt$n$r$p$salt$hash``
  * tokens    -> compact ``base64(header).base64(payload).base64(hmac-sha256)``
                 signed with ``SECRET_KEY``; payload is ``{sub, exp, iat, role}``

Refresh-token rotation, MFA, and revocation lists are Phase 12; this is the
minimum real auth the dashboard needs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from security.config import get_settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


# --------------------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith("scrypt$"):
        return False
    try:
        _, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        expected = _unb64(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# --------------------------------------------------------------------------- tokens


class TokenError(Exception):
    """Invalid, malformed, or expired token."""


def create_access_token(*, user_id: str, role: str, ttl_seconds: int | None = None) -> str:
    settings = get_settings()
    ttl = ttl_seconds or settings.access_token_ttl_seconds
    now = int(time.time())
    payload = {"sub": user_id, "role": role, "iat": now, "exp": now + ttl}
    header = {"alg": "HS256", "typ": "TOI"}
    signing_input = f"{_b64(_dumps(header))}.{_b64(_dumps(payload))}"
    sig = _sign(signing_input)
    return f"{signing_input}.{_b64(sig)}"


def decode_access_token(token: str) -> dict:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    signing_input = f"{header_b64}.{payload_b64}"
    if not hmac.compare_digest(_sign(signing_input), _unb64(sig_b64)):
        raise TokenError("bad signature")
    try:
        payload = json.loads(_unb64(payload_b64))
    except (ValueError, TypeError) as exc:
        raise TokenError("bad payload") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("expired")
    return payload


# --------------------------------------------------------------------------- helpers


def _sign(data: str) -> bytes:
    key = get_settings().secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).digest()


def _dumps(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
