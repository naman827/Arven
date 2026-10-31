"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, conversations, documents, memory, reports, research, settings
from app.config import get_settings
from app.db.session import dispose_engine, init_db, mark_interrupted_jobs
from app.logging import setup_logging
from app.services.container import build_services, get_services, set_services
from app.services.memory import wait_for_learning

log = logging.getLogger("arven")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    cfg = get_settings()
    for d in (cfg.data_dir, cfg.uploads_dir, cfg.reports_dir):
        d.mkdir(parents=True, exist_ok=True)
    await init_db()
    interrupted = await mark_interrupted_jobs()
    if interrupted:
        log.info("marked %d interrupted research job(s) as failed", interrupted)
    try:
        get_services()
    except RuntimeError:
        set_services(build_services(cfg))
    services = get_services()
    log.info(
        "providers: gemini=%s nvidia=%s search=%s",
        "configured" if services.router.providers[0].configured else "missing",
        "configured" if services.router.providers[1].configured else "missing",
        "available" if services.search.available else "unavailable",
    )
    yield
    await services.jobs.shutdown()
    await wait_for_learning()
    await services.search.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title="ARVEN AI", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    base_origin = cfg.frontend_origin.rstrip("/")
    origins = {base_origin, base_origin.replace("localhost", "127.0.0.1"), base_origin.replace("127.0.0.1", "localhost")}
    max_body = (cfg.max_upload_mb + 1) * 1024 * 1024

    # Middleware added later wraps earlier ones; CORS is added after these so their error
    # responses still carry CORS headers and the browser can read them.
    @app.middleware("http")
    async def require_access(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not auth.is_authorized(request, cfg):
            return JSONResponse({"detail": "Login required"}, status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def check_origin(request: Request, call_next):  # type: ignore[no-untyped-def]
        # CORS does not stop "simple" cross-site requests (e.g. form or multipart POSTs) from being sent,
        # so state-changing requests from a foreign Origin are rejected outright.
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in origins:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def limit_body(request: Request, call_next):  # type: ignore[no-untyped-def]
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(origins),
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID", "Authorization"],
        expose_headers=["Content-Disposition"],  # PDF filename for cross-origin downloads
    )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error: %s", type(exc).__name__, exc_info=exc)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    for module in (auth, chat, conversations, research, documents, reports, settings, memory):
        app.include_router(module.router)
    # Added last so it runs first: reject any Host header that is not ours (DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in cfg.allowed_hosts.split(",") if h.strip()])
    return app


app = create_app()
