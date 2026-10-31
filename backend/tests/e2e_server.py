"""Backend for UI end-to-end tests: the real app with scripted fake model/search providers.

No real API calls are made. Run from backend/:  python -m tests.e2e_server  (listens on 127.0.0.1:8001)
"""

import asyncio
import json
import os
import re
import tempfile

import uvicorn

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="arven-e2e-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.environ['DATA_DIR']}/e2e.db".replace("\\", "/"))
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5174")
for key in ("GEMINI_API_KEY", "NVIDIA_API_KEY", "TAVILY_API_KEY"):
    os.environ[key] = ""

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.container import Services, set_services  # noqa: E402
from app.services.providers.router import ProviderRouter  # noqa: E402
from app.services.research.jobs import JobManager  # noqa: E402
from app.services.research.orchestrator import DeepResearchOrchestrator  # noqa: E402
from app.services.search import service as search_service_mod  # noqa: E402
from app.services.search import url_safety  # noqa: E402
from app.services.search.service import SearchService  # noqa: E402
from tests.conftest import FakeProvider, FakeSearchProvider, research_handler  # noqa: E402


def handler(messages, json_mode):  # type: ignore[no-untyped-def]
    system = messages[0].content if messages else ""
    if "memory extraction step" in system:
        found = re.search(r"I am an? ([a-z ]{3,40}?)[.,]", messages[1].content)
        return json.dumps({"memories": [f"The user is a {found.group(1)}."] if found else []})
    if "careful research assistant" in system:  # Chat mode
        question = messages[-1].content
        memories = re.findall(r"(?m)^- (.+)$", system.split("<user_memories>")[1]) if "<user_memories>" in system else []
        return (
            f"Here is a mocked answer to: **{question[:80]}**\n\n"
            + (f"Personalized with {len(memories)} saved memories.\n\n" if memories else "")
            + "- Point one with `inline code`\n- Point two\n\n| Column | Value |\n|---|---|\n| A | 1 |\n\n"
            "```python\nprint('hello from ARVEN')\n```"
        )
    return research_handler(messages, json_mode)


class SlowFake(FakeProvider):
    async def generate(self, messages, **kw):  # type: ignore[no-untyped-def, override]
        await asyncio.sleep(0.25)
        return await super().generate(messages, **kw)

    async def stream(self, messages, **kw):  # type: ignore[no-untyped-def, override]
        async for piece in super().stream(messages, **kw):
            await asyncio.sleep(0.03)
            yield piece


async def _allow(_url: str) -> None:
    return None


def build() -> None:
    settings = get_settings()
    search_service_mod.resolve_and_check = _allow  # type: ignore[assignment]
    url_safety.resolve_and_check = _allow  # type: ignore[assignment]
    router = ProviderRouter(
        [SlowFake("gemini", handler=handler, model="mock-gemini"), FakeProvider("nvidia", model="mock-nvidia")], settings
    )
    search = SearchService([FakeSearchProvider()], settings)
    jobs = JobManager()
    set_services(Services(settings, router, search, jobs, DeepResearchOrchestrator(router, search, jobs, settings)))


if __name__ == "__main__":
    build()
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8001")), log_level="warning")
