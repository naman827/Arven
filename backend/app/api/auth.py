"""Optional access password for deployed instances.

When ACCESS_PASSWORD is empty (local use) every request is allowed. When it is set, /api requests need a
token from POST /api/auth/login, sent as "Authorization: Bearer <token>". Tokens are never accepted in URLs.
"""

import asyncio
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import Settings, get_settings, secret

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_TTL_SECONDS = 7 * 24 * 3600
MIN_PASSWORD_LENGTH = 12
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/status"}
# Every login attempt (right or wrong) waits its turn and is delayed before the password is compared, so
# guessing is capped at about one try per second across all clients. Client addresses behind a hosting proxy
# are spoofable (X-Forwarded-For), so the limit is global. Attempts beyond a short queue get 429. During a
# flood the owner may have to retry, but browsers that are already signed in keep working (7-day tokens).
ATTEMPT_DELAY_SECONDS = 1.0
MAX_QUEUED_ATTEMPTS = 5
_attempt_lock = asyncio.Lock()
_queued = 0
# Fallback when SESSION_SECRET is not set: tokens then stop working when the process restarts.
_PROCESS_SECRET = secrets.token_bytes(32)


def _signing_key() -> bytes:
    # A random server secret, not the password: a leaked token cannot be used to test password guesses offline.
    configured = secret(get_settings().session_secret)
    return hashlib.sha256(configured.encode()).digest() if configured else _PROCESS_SECRET


def _sign(expires: str, password: str) -> str:
    # The password's hash is part of the signed message, so changing ACCESS_PASSWORD revokes every token.
    message = f"{expires}.{hashlib.sha256(password.encode()).hexdigest()}".encode()
    return hmac.new(_signing_key(), message, hashlib.sha256).hexdigest()


def issue_token(password: str, now: float | None = None) -> str:
    expires = str(int((now or time.time()) + TOKEN_TTL_SECONDS))
    return f"{expires}.{_sign(expires, password)}"


def token_valid(token: str, password: str, now: float | None = None) -> bool:
    expires, _, sig = token.partition(".")
    if not expires.isdigit() or not sig:
        return False
    return hmac.compare_digest(sig, _sign(expires, password)) and int(expires) > (now or time.time())


def request_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def is_authorized(request: Request, cfg: Settings) -> bool:
    password = secret(cfg.access_password)
    if not password or request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS or not request.url.path.startswith("/api"):
        return True
    return token_valid(request_token(request), password)


class LoginIn(BaseModel):
    password: str


@router.get("/status")
async def status(request: Request) -> dict[str, bool]:
    password = secret(get_settings().access_password)
    return {"required": bool(password), "authenticated": not password or token_valid(request_token(request), password)}


@router.post("/login")
async def login(body: LoginIn) -> dict[str, str | int]:
    password = secret(get_settings().access_password)
    if not password:
        return {"token": "", "expires_in": 0}
    global _queued
    if _queued >= MAX_QUEUED_ATTEMPTS:
        raise HTTPException(429, "Too many login attempts right now. Try again in a few seconds.")
    _queued += 1
    try:
        async with _attempt_lock:
            await asyncio.sleep(ATTEMPT_DELAY_SECONDS)
            ok = hmac.compare_digest(body.password.encode(), password.encode())
    finally:
        _queued -= 1
    if not ok:
        raise HTTPException(401, "Wrong password")
    return {"token": issue_token(password), "expires_in": TOKEN_TTL_SECONDS}

