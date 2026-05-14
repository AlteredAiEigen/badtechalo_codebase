"""Map OpenAI SDK errors to HTTP responses for clearer API behavior."""

from __future__ import annotations

from fastapi import HTTPException
from openai import (
    APIStatusError,
    AuthenticationError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)


def http_exception_from_openai(exc: BaseException) -> HTTPException:  # noqa: BLE001
    if isinstance(exc, AuthenticationError):
        return HTTPException(
            status_code=401,
            detail={
                "message": "OpenAI rejected the API key.",
                "hint": "Set OPENAI_API_KEY or OPENAI_KEY to a valid secret from "
                "https://platform.openai.com/api-keys and restart uvicorn. "
                "If the key was pasted in chat or committed, rotate it and use the new one.",
            },
        )
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=403,
            detail={"message": "OpenAI permission denied.", "error": str(exc)},
        )
    if isinstance(exc, RateLimitError):
        return HTTPException(
            status_code=429,
            detail={"message": "OpenAI rate limit.", "error": str(exc)},
        )
    if isinstance(exc, APIStatusError):
        return HTTPException(
            status_code=502,
            detail={"message": "OpenAI API error.", "error": str(exc)},
        )
    if isinstance(exc, OpenAIError):
        return HTTPException(
            status_code=502,
            detail={"message": "OpenAI error.", "error": str(exc)},
        )
    return HTTPException(status_code=502, detail={"message": str(exc)})
