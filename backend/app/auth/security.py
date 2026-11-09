"""Signed opaque sessions; no client-provided identity/tenant/role claims."""

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

COOKIE_NAME = "hr_session"
COOKIE_PATH = "/api/v1"
HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        valid = HASHER.verify(password_hash or DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return valid and password_hash is not None


@dataclass(frozen=True, slots=True)
class Session:
    user_id: UUID
    company_id: UUID
    csrf_token: str
    expires_at: float


class SessionStore:
    """Single-process demo: restart invalidates sessions; run one API worker."""

    def __init__(self, secret: str, ttl: int, clock: Callable[[], float] = time.time):
        self._key = secret.encode()
        self._ttl = ttl
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _signature(self, opaque: str) -> str:
        return hmac.new(self._key, opaque.encode(), hashlib.sha256).hexdigest()

    def _lookup_key(self, token: str) -> str | None:
        if len(token) > 256 or token.count(".") != 1:
            return None
        opaque, signature = token.split(".")
        if not hmac.compare_digest(
            self._signature(opaque).encode(), signature.encode()
        ):
            return None
        return hashlib.sha256(opaque.encode()).hexdigest()

    def create(self, user_id: UUID, company_id: UUID) -> tuple[str, Session]:
        opaque = secrets.token_urlsafe(32)
        token = opaque + "." + self._signature(opaque)
        session = Session(
            user_id, company_id, secrets.token_urlsafe(32), self._clock() + self._ttl
        )
        with self._lock:
            now = self._clock()
            self._sessions = {
                k: v for k, v in self._sessions.items() if v.expires_at > now
            }
            self._sessions[hashlib.sha256(opaque.encode()).hexdigest()] = session
        return token, session

    def resolve(self, token: str) -> Session | None:
        key = self._lookup_key(token)
        if key is None:
            return None
        with self._lock:
            session = self._sessions.get(key)
            if session is not None and session.expires_at <= self._clock():
                self._sessions.pop(key, None)
                return None
            return session

    def revoke(self, token: str) -> None:
        key = self._lookup_key(token)
        if key is not None:
            with self._lock:
                self._sessions.pop(key, None)
