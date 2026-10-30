"""Optional access password for deployed instances.

When ACCESS_PASSWORD is empty (local use) every request is allowed. When it is set, /api requests need a
token from POST /api/auth/login, sent as "Authorization: Bearer <token>". Tokens are never accepted in URLs.
"""

import asyncio
import hashlib
import hmac
import secrets
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import Settings, get_settings, secret

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_TTL_SECONDS = 7 * 24 * 3600
MIN_PASSWORD_LENGTH = 12
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/status"}
# One global budget of failed logins. Client addresses behind a hosting proxy cannot be trusted
# (X-Forwarded-For is client-controlled), so failures are not tracked per client.
_MAX_FAILURES, _FAILURE_WINDOW = 20, 600.0
_failures: deque[float] = deque()
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
    now = time.monotonic()
    while _failures and now - _failures[0] > _FAILURE_WINDOW:
        _failures.popleft()
    if len(_failures) >= _MAX_FAILURES:
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    if not hmac.compare_digest(body.password.encode(), password.encode()):
        _failures.append(now)
        await asyncio.sleep(1)  # slows down guessing
        raise HTTPException(401, "Wrong password")
    return {"token": issue_token(password), "expires_in": TOKEN_TTL_SECONDS}
