"""Logging setup with secret redaction."""

import logging
import re

from app.config import get_settings, secret

_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|x-goog-api-key|token)([\"'\s:=]+)([A-Za-z0-9_\-\.]{8,})"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"nvapi-[0-9A-Za-z_\-]{10,}"),
    re.compile(r"tvly-[0-9A-Za-z_\-]{10,}"),
]


def redact(text: str) -> str:
    settings = get_settings()
    for value in (secret(settings.gemini_api_key), secret(settings.nvidia_api_key), secret(settings.tavily_api_key)):
        if value and len(value) >= 6:
            text = text.replace(value, "[REDACTED]")
    for pattern in _PATTERNS:
        if pattern.groups == 3:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = redact(message)
        record.args = None
        return True


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for noisy in ("httpx", "httpcore", "google_genai", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
