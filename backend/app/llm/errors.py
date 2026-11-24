"""Provider-neutral LLM errors. Provider SDK exceptions are mapped onto these by the gateway."""

from typing import Literal

LLMErrorCode = Literal["LLM_TIMEOUT", "RATE_LIMITED", "LLM_UNAVAILABLE"]


class LLMError(Exception):
    code: LLMErrorCode = "LLM_UNAVAILABLE"
    retryable: bool = True


class LLMTimeout(LLMError):
    code: LLMErrorCode = "LLM_TIMEOUT"


class LLMRateLimited(LLMError):
    code: LLMErrorCode = "RATE_LIMITED"


class LLMUnavailable(LLMError):
    """Every attempt on the primary and the fallback failed. `cause` is the code of the last failure."""

    code: LLMErrorCode = "LLM_UNAVAILABLE"
    retryable = True

    def __init__(self, cause: LLMErrorCode, detail: str = "") -> None:
        super().__init__(f"{cause}: {detail}" if detail else cause)
        self.cause = cause
