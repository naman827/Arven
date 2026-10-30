"""Provider routing, fallback, retries, circuit breaker, streaming reset, error classification, secrecy."""

import httpx
import openai
import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.config import Settings
from app.logging import redact
from app.services.providers.base import ChatMessage
from app.services.providers.circuit_breaker import CircuitBreaker, CircuitState
from app.services.providers.errors import AllProvidersFailedError, ErrorKind, ProviderError
from app.services.providers.gemini import GeminiProvider, classify_gemini_error
from app.services.providers.nvidia import classify_openai_error
from app.services.providers.router import ProviderRouter
from tests.conftest import FakeProvider, no_sleep, provider_error

MSG = [ChatMessage("user", "hi")]


async def test_gemini_preferred_when_healthy(make_router):
    g, n = FakeProvider("gemini"), FakeProvider("nvidia")
    out = await make_router(g, n).generate(MSG)
    assert out.provider == "gemini" and g.calls == 1 and n.calls == 0


async def test_nvidia_used_when_gemini_not_configured(make_router):
    g, n = FakeProvider("gemini", configured=False), FakeProvider("nvidia")
    router = make_router(g, n)
    out = await router.generate(MSG)
    assert out.provider == "nvidia" and g.calls == 0
    assert router.overall_status() == "nvidia_fallback_active"


async def test_invalid_key_falls_back_and_is_not_retried(make_router):
    g = FakeProvider("gemini", script=[provider_error("auth")])
    n = FakeProvider("nvidia")
    router = make_router(g, n)
    out = await router.generate(MSG)
    assert out.provider == "nvidia" and g.calls == 1
    assert router.breakers["gemini"].needs_credentials
    await router.generate(MSG)
    assert g.calls == 1, "gemini must not be called again with a bad key"
    assert router.provider_status(g)["state"] == "key_missing_or_invalid"


async def test_429_with_short_retry_after_retries_same_provider(make_router):
    g = FakeProvider("gemini", script=[provider_error("rate_limit", retry_after=1.0), "fine"])
    n = FakeProvider("nvidia")
    out = await make_router(g, n).generate(MSG)
    assert out.text == "fine" and out.provider == "gemini" and n.calls == 0


async def test_429_with_long_retry_after_falls_back_immediately(make_router):
    g = FakeProvider("gemini", script=[provider_error("rate_limit", retry_after=120.0)])
    n = FakeProvider("nvidia")
    router = make_router(g, n)
    out = await router.generate(MSG)
    assert out.provider == "nvidia" and g.calls == 1
    assert router.breakers["gemini"].state == CircuitState.OPEN


async def test_429_without_retry_after_uses_bounded_backoff(settings: Settings):
    waits: list[float] = []

    async def record(s: float) -> None:
        waits.append(s)

    g = FakeProvider("gemini", script=[provider_error("rate_limit")] * 10)
    n = FakeProvider("nvidia")
    router = ProviderRouter([g, n], settings, sleep=record)
    out = await router.generate(MSG)
    assert out.provider == "nvidia"
    assert g.calls == settings.max_retry_attempts + 1
    assert len(waits) == settings.max_retry_attempts and waits[1] > waits[0] * 1.2 - 0.01


async def test_quota_exhausted_no_retry_long_cooldown(make_router, settings):
    g = FakeProvider("gemini", script=[provider_error("quota")])
    n = FakeProvider("nvidia")
    router = make_router(g, n)
    assert (await router.generate(MSG)).provider == "nvidia"
    assert g.calls == 1
    assert router.breakers["gemini"].seconds_until_retry() > settings.provider_cooldown_seconds


async def test_server_errors_retry_then_fallback(make_router, settings):
    g = FakeProvider("gemini", script=[provider_error("server")] * 5)
    n = FakeProvider("nvidia")
    out = await make_router(g, n).generate(MSG)
    assert out.provider == "nvidia" and g.calls == settings.max_retry_attempts + 1


async def test_timeout_then_success_on_retry(make_router):
    g = FakeProvider("gemini", script=[provider_error("timeout"), "ok"])
    assert (await make_router(g, FakeProvider("nvidia")).generate(MSG)).provider == "gemini"


async def test_bad_request_is_not_sent_to_other_provider(make_router):
    g = FakeProvider("gemini", script=[provider_error("bad_request")])
    n = FakeProvider("nvidia")
    with pytest.raises(ProviderError) as info:
        await make_router(g, n).generate(MSG)
    assert info.value.kind == ErrorKind.BAD_REQUEST and n.calls == 0


async def test_model_not_found_falls_back(make_router):
    g = FakeProvider("gemini", script=[provider_error("model_not_found")])
    assert (await make_router(g, FakeProvider("nvidia")).generate(MSG)).provider == "nvidia"


async def test_both_down_gives_clear_error(make_router):
    g = FakeProvider("gemini", script=[provider_error("quota")])
    n = FakeProvider("nvidia", script=[provider_error("auth", provider="nvidia")])
    with pytest.raises(AllProvidersFailedError) as info:
        await make_router(g, n).generate(MSG)
    assert "gemini" in info.value.message and "nvidia" in info.value.message


async def test_no_providers_configured(make_router):
    router = make_router(FakeProvider("gemini", configured=False), FakeProvider("nvidia", configured=False))
    with pytest.raises(AllProvidersFailedError) as info:
        await router.generate(MSG)
    assert "GEMINI_API_KEY" in info.value.message
    assert router.overall_status() == "key_missing_or_invalid"


async def test_cooldown_then_recovery_to_gemini(settings):
    now = [1000.0]
    breakers = {
        "gemini": CircuitBreaker(cooldown_seconds=30, quota_cooldown_seconds=600, clock=lambda: now[0]),
        "nvidia": CircuitBreaker(cooldown_seconds=30, quota_cooldown_seconds=600, clock=lambda: now[0]),
    }
    g = FakeProvider("gemini", script=[provider_error("rate_limit", retry_after=60)])
    n = FakeProvider("nvidia")
    router = ProviderRouter([g, n], settings, sleep=no_sleep, breakers=breakers)
    assert (await router.generate(MSG)).provider == "nvidia"
    assert (await router.generate(MSG)).provider == "nvidia"
    assert router.overall_status() == "nvidia_fallback_active"
    now[0] += 61  # cooldown elapsed -> half-open probe goes to gemini
    assert breakers["gemini"].state == CircuitState.HALF_OPEN
    assert (await router.generate(MSG)).provider == "gemini"
    assert breakers["gemini"].state == CircuitState.CLOSED
    assert router.overall_status() == "gemini_active"


async def test_half_open_failure_reopens(settings):
    now = [0.0]
    b = CircuitBreaker(cooldown_seconds=10, clock=lambda: now[0])
    b.record_failure(provider_error("rate_limit", retry_after=5))
    now[0] = 6
    assert b.state == CircuitState.HALF_OPEN
    b.record_failure(provider_error("server"))
    assert b.state == CircuitState.OPEN


async def test_stream_failure_after_partial_output_resets_and_does_not_duplicate(make_router):
    g = FakeProvider("gemini", stream_script=[["Hello ", "wor", provider_error("server")]])
    n = FakeProvider("nvidia", stream_script=[["Complete ", "answer."]])
    router = make_router(g, n)
    text, resets, providers = "", 0, []
    async for ev in router.stream(MSG):
        if ev.type == "token":
            text += ev.text
        elif ev.type == "reset":
            resets += 1
            text = ""
        elif ev.type == "provider":
            providers.append(ev.provider)
    assert resets == 1 and text == "Complete answer." and providers == ["gemini", "nvidia"]
    assert g.stream_calls == 1, "after partial output we switch to the backup instead of retrying"


async def test_stream_failure_before_output_falls_back_without_reset(make_router):
    g = FakeProvider("gemini", stream_script=[provider_error("quota")])
    n = FakeProvider("nvidia", stream_script=[["ok"]])
    events = [ev async for ev in make_router(g, n).stream(MSG)]
    assert [e.type for e in events] == ["provider", "provider", "token"]


async def test_stream_both_fail_raises(make_router):
    g = FakeProvider("gemini", stream_script=[provider_error("auth")])
    n = FakeProvider("nvidia", stream_script=[provider_error("auth", provider="nvidia")])
    with pytest.raises(AllProvidersFailedError):
        [ev async for ev in make_router(g, n).stream(MSG)]


class Thing(BaseModel):
    name: str
    count: int


async def test_structured_output_repair_retry():
    p = FakeProvider("gemini", script=['{"name": "x"}', '```json\n{"name": "x", "count": 2}\n```'])
    out = await p.generate_structured(MSG, Thing)
    assert out.count == 2 and p.calls == 2


async def test_structured_output_gives_up_after_one_repair():
    p = FakeProvider("gemini", script=["nope", "still nope"])
    with pytest.raises(ProviderError) as info:
        await p.generate_structured(MSG, Thing)
    assert info.value.kind == ErrorKind.INVALID_OUTPUT


# ---- classification of real SDK errors -------------------------------------


def test_classify_gemini_errors():
    rate = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Resource exhausted",
                "status": "RESOURCE_EXHAUSTED",
                "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}],
            }
        },
    )
    err = classify_gemini_error(rate)
    assert err.kind == ErrorKind.RATE_LIMIT and err.retry_after == 7.0

    daily = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota, please check your plan and billing details.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
            }
        },
    )
    assert classify_gemini_error(daily).kind == ErrorKind.QUOTA

    bad_key = genai_errors.ClientError(
        400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}
    )
    assert classify_gemini_error(bad_key).kind == ErrorKind.AUTH
    assert (
        classify_gemini_error(
            genai_errors.ClientError(403, {"error": {"code": 403, "message": "denied", "status": "PERMISSION_DENIED"}})
        ).kind
        == ErrorKind.PERMISSION
    )
    assert (
        classify_gemini_error(
            genai_errors.ClientError(404, {"error": {"code": 404, "message": "models/x is not found", "status": "NOT_FOUND"}})
        ).kind
        == ErrorKind.MODEL_NOT_FOUND
    )
    assert (
        classify_gemini_error(
            genai_errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
        ).kind
        == ErrorKind.SERVER
    )
    assert (
        classify_gemini_error(
            genai_errors.ClientError(400, {"error": {"code": 400, "message": "bad field", "status": "INVALID_ARGUMENT"}})
        ).kind
        == ErrorKind.BAD_REQUEST
    )
    assert classify_gemini_error(httpx.ConnectTimeout("t")).kind == ErrorKind.TIMEOUT
    assert classify_gemini_error(httpx.ConnectError("c")).kind == ErrorKind.NETWORK


def _openai_status(code: int, headers: dict[str, str] | None = None, message: str = "err") -> openai.APIStatusError:
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    response = httpx.Response(code, headers=headers or {}, request=request)
    cls = {
        401: openai.AuthenticationError,
        403: openai.PermissionDeniedError,
        404: openai.NotFoundError,
        429: openai.RateLimitError,
        400: openai.BadRequestError,
    }.get(code, openai.InternalServerError)
    return cls(message, response=response, body=None)


def test_classify_openai_errors():
    assert classify_openai_error(_openai_status(401)).kind == ErrorKind.AUTH
    rl = classify_openai_error(_openai_status(429, {"retry-after": "3"}))
    assert rl.kind == ErrorKind.RATE_LIMIT and rl.retry_after == 3.0
    assert classify_openai_error(_openai_status(429, message="quota exceeded")).kind == ErrorKind.QUOTA
    assert classify_openai_error(_openai_status(404)).kind == ErrorKind.MODEL_NOT_FOUND
    assert classify_openai_error(_openai_status(400)).kind == ErrorKind.BAD_REQUEST
    assert classify_openai_error(_openai_status(502)).kind == ErrorKind.SERVER
    req = httpx.Request("POST", "https://x")
    assert classify_openai_error(openai.APITimeoutError(request=req)).kind == ErrorKind.TIMEOUT
    assert classify_openai_error(openai.APIConnectionError(request=req)).kind == ErrorKind.NETWORK


# ---- secrecy ----------------------------------------------------------------


def test_secrets_redacted_from_logs(monkeypatch, settings):
    from app.config import get_settings

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTESTSECRETVALUE1234567890")
    get_settings.cache_clear()
    text = redact("calling with key AIzaSyTESTSECRETVALUE1234567890 and Authorization: Bearer nvapi-abcdef1234567890xyz")
    assert "TESTSECRET" not in text and "nvapi-abcdef" not in text
    get_settings.cache_clear()


async def test_status_never_contains_key(monkeypatch, settings):
    from app.config import get_settings

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTESTSECRETVALUE1234567890")
    get_settings.cache_clear()
    s = get_settings()
    g = GeminiProvider(s)
    router = ProviderRouter([g], s, sleep=no_sleep)
    router.breakers["gemini"].record_failure(ProviderError(ErrorKind.AUTH, "gemini", "key AIzaSyTESTSECRETVALUE1234567890 invalid"))
    status = str(router.provider_status(g)) + str(router.overall_status())
    assert "TESTSECRET" not in status
    get_settings.cache_clear()


def test_strip_reasoning_removes_think_blocks():
    from app.services.providers.nvidia import strip_reasoning

    assert strip_reasoning("<think>plan it</think>\n\n{\"a\": 1}") == '{"a": 1}'
    assert strip_reasoning("reasoning without open tag</think>Answer") == "Answer"
    assert strip_reasoning("<think>never closed") == ""
    assert strip_reasoning("Plain answer") == "Plain answer"


def test_reasoning_filter_handles_split_tags():
    from app.services.providers.nvidia import ReasoningFilter

    f = ReasoningFilter()
    chunks = ["<thi", "nk>secret ", "steps</th", "ink>\n\nHello ", "<", "b>world</b>"]
    out = "".join(f.feed(c) for c in chunks) + f.flush()
    assert out == "Hello <b>world</b>"
    f2 = ReasoningFilter()
    assert "".join(f2.feed(c) for c in ["No ", "tags", " here"]) + f2.flush() == "No tags here"
