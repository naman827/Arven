"""Optional access password for deployed instances.

When ACCESS_PASSWORD is empty (local use) every request is allowed. When it is set, /api requests need a
token from POST /api/auth/login, sent as "Authorization: Bearer <token>". EventSource streams and PDF links
cannot set headers, so GET requests may pass it as ?access_token=<token> instead.
"""

import asyncio
import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import Settings, get_settings, secret

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_TTL_SECONDS = 7 * 24 * 3600
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/status"}
_MAX_FAILURES, _FAILURE_WINDOW = 10, 600.0
_failures: dict[str, deque[float]] = defaultdict(deque)


def _key(password: str) -> bytes:
    # Changing ACCESS_PASSWORD changes the key, which invalidates every issued token.
    return hashlib.sha256(f"arven-access:{password}".encode()).digest()


def issue_token(password: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + TOKEN_TTL_SECONDS)
    sig = hmac.new(_key(password), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def token_valid(token: str, password: str, now: float | None = None) -> bool:
    expires, _, sig = token.partition(".")
    if not expires.isdigit() or not sig:
        return False
    expected = hmac.new(_key(password), expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected) and int(expires) > (now or time.time())


def request_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if request.method == "GET":
        return request.query_params.get("access_token", "")
    return ""


def is_authorized(request: Request, cfg: Settings) -> bool:
    password = secret(cfg.access_password)
    if not password or request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS or not request.url.path.startswith("/api"):
        return True
    return token_valid(request_token(request), password)


def _client(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


class LoginIn(BaseModel):
    password: str


@router.get("/status")
async def status(request: Request) -> dict[str, bool]:
    cfg = get_settings()
    password = secret(cfg.access_password)
    return {"required": bool(password), "authenticated": not password or token_valid(request_token(request), password)}


@router.post("/login")
async def login(body: LoginIn, request: Request) -> dict[str, str | int]:
    password = secret(get_settings().access_password)
    if not password:
        return {"token": "", "expires_in": 0}
    client = _client(request)
    attempts = _failures[client]
    now = time.monotonic()
    while attempts and now - attempts[0] > _FAILURE_WINDOW:
        attempts.popleft()
    if len(attempts) >= _MAX_FAILURES:
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    if not hmac.compare_digest(body.password.encode(), password.encode()):
        attempts.append(now)
        await asyncio.sleep(1)  # slows down guessing
        raise HTTPException(401, "Wrong password")
    attempts.clear()
    return {"token": issue_token(password), "expires_in": TOKEN_TTL_SECONDS}
