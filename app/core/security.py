"""Password hashing (Argon2) and JWT access/refresh tokens."""
from datetime import timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .common import utcnow
from .config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _make_token(sub: str, role: str, kind: str, delta: timedelta) -> str:
    s = get_settings()
    now = utcnow()
    payload = {"sub": sub, "role": role, "type": kind, "iat": now, "exp": now + delta}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> str:
    return _make_token(user_id, role, "access", timedelta(minutes=get_settings().access_token_minutes))


def create_refresh_token(user_id: str, role: str) -> str:
    return _make_token(user_id, role, "refresh", timedelta(days=get_settings().refresh_token_days))


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any problem (bad signature, expired, wrong type)."""
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Wrong token type")
    return payload
