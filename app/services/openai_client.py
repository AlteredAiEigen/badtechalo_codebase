"""Single OpenAI client factory (lazy, avoids import-time httpx/OpenAI init issues)."""

from __future__ import annotations

from openai import OpenAI

from app.config_env import get_openai_key


def get_openai_client() -> OpenAI:
    """New client each call so OPENAI_KEY / OPENAI_API_KEY changes are picked up after reload."""
    return OpenAI(api_key=get_openai_key())
