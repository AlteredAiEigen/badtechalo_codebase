"""Single OpenAI client factory (lazy, avoids import-time httpx/OpenAI init issues)."""

from __future__ import annotations

import os
import ssl

import httpx
from openai import OpenAI

from app.config_env import get_openai_key

_DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=60.0)


def get_openai_client() -> OpenAI:
    """
    New client each call so OPENAI_KEY / OPENAI_API_KEY changes are picked up after reload.

    SSL / connectivity:
    - Default ``verify`` uses ``ssl.create_default_context()`` so Windows/macOS **system**
      trust stores are used (helps corporate TLS inspection roots). Plain httpx defaults lean on
      certifi and can fail with "connection" / certificate errors on some networks.
    - Set ``SSL_CERT_FILE`` or ``REQUESTS_CA_BUNDLE`` to a PEM bundle to trust a specific CA.
    - Dev-only: ``OPENAI_INSECURE_SSL=1`` disables certificate verification (not for production).
    - Proxies: set ``HTTPS_PROXY`` / ``HTTP_PROXY`` in the environment (httpx honors them by default).
    """
    key = get_openai_key()
    insecure = os.getenv("OPENAI_INSECURE_SSL", "").strip().lower() in ("1", "true", "yes")
    ca_bundle = (os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE") or "").strip()

    if insecure:
        http_client = httpx.Client(verify=False, timeout=_DEFAULT_TIMEOUT, trust_env=True)
    elif ca_bundle:
        http_client = httpx.Client(verify=ca_bundle, timeout=_DEFAULT_TIMEOUT, trust_env=True)
    else:
        http_client = httpx.Client(
            verify=ssl.create_default_context(),
            timeout=_DEFAULT_TIMEOUT,
            trust_env=True,
        )

    return OpenAI(api_key=key, http_client=http_client)