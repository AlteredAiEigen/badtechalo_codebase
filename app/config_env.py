"""Environment loading and OpenAI key resolution (supports OPENAI_API_KEY or OPENAI_KEY)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# backend/app/config_env.py -> repo root is parent of `app`
_REPO_ROOT = Path(__file__).resolve().parents[1]

# Public for path validation in API
REPO_ROOT = _REPO_ROOT

_loaded = False


def load_all_dotenv() -> None:
    """Load .env from repo root, then app/.env (app wins). Idempotent-ish; safe to call often."""
    global _loaded  # noqa: PLW0603
    root_env = _REPO_ROOT / ".env"
    app_env = _REPO_ROOT / "app" / ".env"
    load_dotenv(root_env, override=False)
    load_dotenv(app_env, override=True)
    _loaded = True


def _normalize_secret(value: str) -> str:
    v = value.strip()
    # Strip UTF-8 BOM if pasted from some editors
    if v.startswith("\ufeff"):
        v = v.lstrip("\ufeff").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def get_openai_key() -> str:
    """
    Resolve OpenAI API key.

    **app/.env and repo /.env win over shell environment.** That way an old or placeholder
    `OPENAI_KEY` exported in your terminal / IDE launch config cannot override the real key
    you keep in ``app/.env``.
    """
    load_all_dotenv()
    app_dot = dotenv_values(_REPO_ROOT / "app" / ".env")
    root_dot = dotenv_values(_REPO_ROOT / ".env")
    raw = (
        (app_dot.get("OPENAI_API_KEY") or "").strip()
        or (app_dot.get("OPENAI_KEY") or "").strip()
        or (root_dot.get("OPENAI_API_KEY") or "").strip()
        or (root_dot.get("OPENAI_KEY") or "").strip()
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("OPENAI_KEY")
    )
    key = _normalize_secret(raw or "")
    if key:
        return key
    return ""


def openai_key_diagnostics(key: str) -> dict:
    """
    Non-secret hints about the key string (for /health/config).
    A 401 from OpenAI usually means: wrong key, revoked key, or truncated / placeholder paste.
    """
    k = key.strip()
    out: dict = {
        "present": bool(k),
        "char_length": len(k) if k else 0,
        "starts_with_sk": k.startswith("sk-") if k else False,
        "issues": [],
    }
    if not k:
        out["issues"].append("no_key")
        return out
    if "\n" in k or "\r" in k:
        out["issues"].append("contains_newline_paste_the_key_on_one_line")
    if "..." in k or "…" in k:
        out["issues"].append("contains_ellipsis_use_the_full_key_from_openai_not_a_redacted_copy")
    # Project keys are typically long; short values are almost always wrong
    if len(k) < 40:
        out["issues"].append("suspiciously_short_openai_keys_are_usually_100_plus_chars")
    if not k.startswith("sk-"):
        out["issues"].append("expected_prefix_sk")
    return out


def get_mongodb_uri() -> str:
    load_all_dotenv()
    app_dot = dotenv_values(_REPO_ROOT / "app" / ".env")
    root_dot = dotenv_values(_REPO_ROOT / ".env")
    raw = (
        (app_dot.get("MONGODB_URI") or "").strip()
        or (root_dot.get("MONGODB_URI") or "").strip()
        or os.getenv("MONGODB_URI")
        or ""
    )
    return _normalize_secret(raw or "")


def get_mongodb_db_name() -> str:
    load_all_dotenv()
    app_dot = dotenv_values(_REPO_ROOT / "app" / ".env")
    root_dot = dotenv_values(_REPO_ROOT / ".env")
    raw = (
        (app_dot.get("MONGODB_DB") or "").strip()
        or (root_dot.get("MONGODB_DB") or "").strip()
        or os.getenv("MONGODB_DB")
        or "badtechalo"
    )
    return raw


def get_jwt_secret() -> str:
    load_all_dotenv()
    app_dot = dotenv_values(_REPO_ROOT / "app" / ".env")
    root_dot = dotenv_values(_REPO_ROOT / ".env")
    raw = (
        (app_dot.get("JWT_SECRET") or "").strip()
        or (root_dot.get("JWT_SECRET") or "").strip()
        or os.getenv("JWT_SECRET")
        or "badtechalo-dev-secret-change-in-production"
    )
    return _normalize_secret(raw)


def get_jwt_expire_minutes() -> int:
    load_all_dotenv()
    raw = os.getenv("JWT_EXPIRE_MINUTES") or "10080"
    try:
        return int(raw)
    except ValueError:
        return 10080
