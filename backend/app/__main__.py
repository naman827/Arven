"""Run with: python -m app  (binds to 127.0.0.1 by default)."""

import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    cfg = get_settings()
    if cfg.backend_host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Refusing to bind to a non-local address. ARVEN AI is a local app; set BACKEND_HOST=127.0.0.1.")
    uvicorn.run("app.main:app", host=cfg.backend_host, port=cfg.backend_port, log_level="info")
