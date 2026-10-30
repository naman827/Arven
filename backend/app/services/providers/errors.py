"""Provider error hierarchy. `kind` drives routing decisions."""

from enum import StrEnum


class ErrorKind(StrEnum):
    AUTH = "auth"  # 401 / invalid key
    PERMISSION = "permission"  # 403
    RATE_LIMIT = "rate_limit"  # 429, short-term
    QUOTA = "quota"  # quota/billing exhausted, long-term
    SERVER = "server"  # 5xx
    NETWORK = "network"
    TIMEOUT = "timeout"
    BAD_REQUEST = "bad_request"  # 400 / validation / malformed
    MODEL_NOT_FOUND = "model_not_found"  # missing model / unsupported capability
    NOT_CONFIGURED = "not_configured"
    INVALID_OUTPUT = "invalid_output"  # structured output failed validation
    UNKNOWN = "unknown"


RETRYABLE = {ErrorKind.RATE_LIMIT, ErrorKind.SERVER, ErrorKind.NETWORK, ErrorKind.TIMEOUT}
# Kinds where trying the other provider makes sense.
FALLBACK_OK = RETRYABLE | {
    ErrorKind.AUTH,
    ErrorKind.PERMISSION,
    ErrorKind.QUOTA,
    ErrorKind.MODEL_NOT_FOUND,
    ErrorKind.NOT_CONFIGURED,
    ErrorKind.UNKNOWN,
    # Empty or unparseable output from one model is often fine from the other (it is not retried on the same one).
    ErrorKind.INVALID_OUTPUT,
}

USER_MESSAGES = {
    ErrorKind.AUTH: "API key is missing, invalid, or revoked. Update it in .env and restart the backend.",
    ErrorKind.PERMISSION: "The account or key does not have permission for this model.",
    ErrorKind.RATE_LIMIT: "Rate limit reached. Requests are being slowed down.",
    ErrorKind.QUOTA: "Quota or billing limit exhausted for this provider.",
    ErrorKind.SERVER: "The provider returned a server error.",
    ErrorKind.NETWORK: "Could not reach the provider (network error).",
    ErrorKind.TIMEOUT: "The provider timed out.",
    ErrorKind.BAD_REQUEST: "The provider rejected the request as invalid.",
    ErrorKind.MODEL_NOT_FOUND: "The configured model was not found or does not support this task. Check the model name in .env.",
    ErrorKind.NOT_CONFIGURED: "Provider is not configured (no API key).",
    ErrorKind.INVALID_OUTPUT: "The model returned output that did not match the expected format.",
    ErrorKind.UNKNOWN: "Unexpected provider error.",
}


class ProviderError(Exception):
    def __init__(
        self,
        kind: ErrorKind,
        provider: str,
        detail: str = "",
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.kind = kind
        self.provider = provider
        self.detail = detail[:500]
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"{provider}: {kind.value}: {self.user_message}")

    @property
    def user_message(self) -> str:
        return USER_MESSAGES[self.kind]

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE

    @property
    def fallback_ok(self) -> bool:
        return self.kind in FALLBACK_OK


class AllProvidersFailedError(Exception):
    def __init__(self, errors: list[ProviderError]) -> None:
        self.errors = errors
        if not errors:
            msg = "No model provider is configured. Add GEMINI_API_KEY or NVIDIA_API_KEY to .env and restart the backend."
        else:
            parts = [f"{e.provider}: {e.user_message}" for e in errors]
            msg = "All model providers failed. " + " ".join(parts)
        self.message = msg
        super().__init__(msg)


class GenerationResetError(Exception):
    """Internal marker: stream failed after partial output."""


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
