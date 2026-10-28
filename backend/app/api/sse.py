"""Server-Sent Events formatting."""

import json
from typing import Any

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def format_sse(event: dict[str, Any]) -> str:
    lines = []
    if event.get("id") is not None:
        lines.append(f"id: {event['id']}")
    lines.append(f"event: {event['type']}")
    lines.append("data: " + json.dumps(event.get("data", {}), default=str))
    return "\n".join(lines) + "\n\n"
