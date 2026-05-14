#!/usr/bin/env python3
"""
End-to-end smoke test for fecu101.pdf (from repo root):

  cd /path/to/backend
  python scripts/e2e_fecu101.py

Requires: API running (uvicorn), valid OPENAI_API_KEY or OPENAI_KEY in app/.env.
Uses only first 3 pages for indexing to finish quickly.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    base = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
    print("API:", base)

    r = requests.get(f"{base}/health/config", timeout=10)
    r.raise_for_status()
    cfg = r.json()
    print("health/config:", cfg)
    diag = cfg.get("openai_key_diagnostics") or {}
    if diag.get("issues"):
        print("WARN key shape issues:", diag["issues"])

    if not cfg.get("openai_key_configured"):
        print(
            "FAIL: API does not see an OpenAI key. Put OPENAI_KEY or OPENAI_API_KEY in",
            cfg.get("app_dotenv_path"),
            "and restart uvicorn.",
        )
        return 2

    ho = requests.get(f"{base}/health/openai", timeout=120)
    ho_js = ho.json()
    print("health/openai:", ho_js)
    if ho_js.get("how_to_fix"):
        print("\n>>>", ho_js["how_to_fix"], "\n")
    if not (ho_js.get("embeddings_ok") and ho_js.get("chat_ok")):
        print("FAIL: OpenAI smoke test from API failed.")
        return 3

    ingest = requests.post(
        f"{base}/books/ingest-repo-pdf",
        data={"title": "E2E fecu101", "relative_path": "fecu1dd/fecu101.pdf"},
        timeout=600,
    )
    print("ingest status", ingest.status_code, ingest.text[:500])
    ingest.raise_for_status()
    book_id = ingest.json()["book_id"]
    print("book_id:", book_id)

    idx = requests.post(
        f"{base}/books/{book_id}/index",
        params={"max_pages": 3, "background": False},
        timeout=600,
    )
    print("index start", idx.status_code, idx.text)
    idx.raise_for_status()

    for _ in range(900):
        st = requests.get(f"{base}/books/{book_id}/index-status", timeout=30).json()
        p = st.get("index_progress") or {}
        msg = p.get("message", "")
        print(f"  [{st.get('index_status')}] {msg}")
        if st.get("index_status") == "completed":
            break
        if st.get("index_status") == "failed":
            print("ERROR:", st.get("index_error"))
            return 4
        time.sleep(1.0)
    else:
        print("TIMEOUT waiting for index")
        return 5

    plan = requests.post(
        f"{base}/assignments/generate-plan",
        json={
            "book_id": book_id,
            "title": "E2E homework",
            "learning_objectives": ["Recall key ideas from the excerpt."],
            "scope_query": "first pages summary",
            "notes": "Short plan only.",
        },
        timeout=300,
    )
    print("plan status", plan.status_code)
    if plan.status_code != 200:
        print(plan.text)
        return 6
    print("plan keys:", list(plan.json().keys()))
    print("OK e2e complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
