#!/usr/bin/env python3
"""
Time the RAG indexing step (chunk + embed) against a running API.

  cd /path/to/backend
  python scripts/benchmark_index.py
  python scripts/benchmark_index.py --book-id 2 --max-pages 8
  python scripts/benchmark_index.py --relative-path fecu1dd/fecu101.pdf --background
  python scripts/benchmark_index.py --book-id 2 --max-pages 3 --background --force-restart
  python scripts/benchmark_index.py ... --compact   # single-line terminal redraw

Requires: uvicorn on API_BASE (default http://127.0.0.1:8000), OpenAI key on server.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.index_status_progress import estimate_index_fraction  # noqa: E402


def poll_until_done(
    base: str, book_id: int, interval: float = 0.5, *, compact: bool = False
) -> tuple[bool, float, dict | None]:
    wall0 = time.perf_counter()
    last: dict | None = None
    for _ in range(100_000):
        r = requests.get(f"{base}/books/{book_id}/index-status", timeout=60)
        if r.status_code != 200:
            print("index-status HTTP", r.status_code, r.text[:300])
            return False, time.perf_counter() - wall0, None
        last = r.json()
        status = last.get("index_status")
        frac, label = estimate_index_fraction(last)
        elapsed = time.perf_counter() - wall0
        p = last.get("index_progress") or {}
        msg = p.get("message", "")[:70]
        line = (
            f"[{elapsed:6.1f}s] status={status!s:10} frac={frac*100:5.1f}% ({label})  {msg}"
        )
        if compact:
            print("\r" + line + " " * 8, end="", flush=True)
        else:
            print(line, flush=True)
        if status == "completed":
            print()
            return True, elapsed, last
        if status == "failed":
            print()
            print("index_error:", last.get("index_error"))
            return False, elapsed, last
        time.sleep(interval)
    print()
    return False, time.perf_counter() - wall0, last


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark POST /books/{id}/index + poll.")
    ap.add_argument("--base", default=os.environ.get("API_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--book-id", type=int, default=None, help="Existing book (skip ingest).")
    ap.add_argument("--relative-path", default="", help="Repo-relative PDF path to ingest first.")
    ap.add_argument("--title", default="Benchmark book")
    ap.add_argument("--max-pages", type=int, default=None, help="Limit pages (omit = full PDF).")
    ap.add_argument(
        "--background",
        action="store_true",
        help="Use background indexing + poll (like Streamlit). Default is synchronous index.",
    )
    ap.add_argument("--force-restart", action="store_true")
    ap.add_argument(
        "--compact",
        action="store_true",
        help="Single-line redraw (may buffer when piped). Default: one newline log row per poll.",
    )
    args = ap.parse_args()
    base = args.base.rstrip("/")

    book_id = args.book_id
    if book_id is None:
        rel = args.relative_path or "fecu1dd/fecu101.pdf"
        t0 = time.perf_counter()
        ing = requests.post(
            f"{base}/books/ingest-repo-pdf",
            data={"title": args.title, "relative_path": rel},
            timeout=600,
        )
        ing.raise_for_status()
        book_id = ing.json()["book_id"]
        print(f"ingest done in {time.perf_counter() - t0:.2f}s book_id={book_id}")

    params: dict = {}
    if args.max_pages is not None:
        params["max_pages"] = args.max_pages
    if args.background:
        params["background"] = True
    else:
        params["background"] = False
    if args.force_restart:
        params["force_restart"] = True

    print("POST /index", params)
    t_index = time.perf_counter()
    idx = requests.post(f"{base}/books/{book_id}/index", params=params, timeout=3600)
    if args.background:
        if idx.status_code != 202:
            print("unexpected status", idx.status_code, idx.text)
            return 1
        print(f"202 accepted in {time.perf_counter() - t_index:.2f}s; polling…")
        ok, poll_sec, _ = poll_until_done(base, book_id, compact=args.compact)
        print(f"poll wall time: {poll_sec:.2f}s")
        return 0 if ok else 2

    idx.raise_for_status()
    http_sec = time.perf_counter() - t_index
    print(f"sync index HTTP completed in {http_sec:.2f}s", idx.text[:200])
    st = requests.get(f"{base}/books/{book_id}/index-status", timeout=30).json()
    frac, _ = estimate_index_fraction(st)
    print("final index_status:", st.get("index_status"), "display_frac~", f"{frac*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
