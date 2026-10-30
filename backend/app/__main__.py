"""Run with: python -m app  (binds to 127.0.0.1 by default)."""

import os

import uvicorn

from app.config import get_settings, secret

if __name__ == "__main__":
    cfg = get_settings()
    local = cfg.backend_host in ("127.0.0.1", "localhost", "::1")
    if not local and not secret(cfg.access_password):
        raise SystemExit(
            "Refusing to bind to a non-local address without ACCESS_PASSWORD. Set ACCESS_PASSWORD (deployment) "
            "or BACKEND_HOST=127.0.0.1 (local use)."
        )
    # Hosting platforms such as Render pass the port in $PORT.
    port = int(os.environ.get("PORT", cfg.backend_port))
    uvicorn.run(
        "app.main:app",
        host=cfg.backend_host,
        port=port,
        log_level="info",
        # Deployed: access logs would record ?access_token= query strings, and proxy headers carry the client IP.
        access_log=local,
        proxy_headers=not local,
        forwarded_allow_ips="*" if not local else None,
    )
