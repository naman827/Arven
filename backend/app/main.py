"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, conversations, documents, reports, research, settings
from app.config import get_settings
from app.db.session import dispose_engine, init_db, mark_interrupted_jobs
from app.logging import setup_logging
from app.services.container import build_services, get_services, set_services

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
    await services.search.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title="ARVEN AI", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.frontend_origin, cfg.frontend_origin.replace("localhost", "127.0.0.1")],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    max_body = (cfg.max_upload_mb + 1) * 1024 * 1024

    @app.middleware("http")
    async def limit_body(request: Request, call_next):  # type: ignore[no-untyped-def]
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error: %s", type(exc).__name__, exc_info=exc)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    for module in (chat, conversations, research, documents, reports, settings):
        app.include_router(module.router)
    return app


app = create_app()
