#!/usr/bin/env python3
"""
Full pipeline smoke test:
  1. Health check
  2. Ingest PDF
  3. Index (chunk + embed)
  4. Generate assignment plan
  5. Approve plan
  6. Generate final assignment

Run:
  cd /path/to/backend
  python scripts/smoke_test.py
  python scripts/smoke_test.py --pdf fecu1dd/fecu101.pdf --max-pages 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class Timer:
    def __init__(self, label: str):
        self.label = label
        self.elapsed = 0.0

    def __enter__(self):
        self._t = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed = time.perf_counter() - self._t


def step(num: int, label: str):
    print(f"\n{'='*60}")
    print(f"  STEP {num}: {label}")
    print(f"{'='*60}")


def ok(msg: str, elapsed: float | None = None):
    t = f" ({elapsed:.1f}s)" if elapsed is not None else ""
    print(f"  ✓ {msg}{t}")


def fail(msg: str):
    print(f"  ✗ FAIL: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test the full assignment pipeline.")
    ap.add_argument("--base", default=os.environ.get("API_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--pdf", default="fecu1dd/fecu101.pdf", help="Repo-relative PDF path")
    ap.add_argument("--title", default="Smoke Test Book")
    ap.add_argument("--max-pages", type=int, default=0, help="0 = all pages")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    wall_start = time.perf_counter()

    # ── Step 0: Health ──
    step(0, "Health checks")

    with Timer("root") as t:
        r = requests.get(f"{base}/", timeout=10)
    if r.ok:
        ok(f"API reachable: {r.json().get('message')}", t.elapsed)
    else:
        fail(f"API down: {r.status_code}")
        return 1

    with Timer("openai") as t:
        r = requests.get(f"{base}/health/openai", timeout=120)
    ho = r.json()
    if ho.get("embeddings_ok") and ho.get("chat_ok"):
        ok("OpenAI embeddings + chat working", t.elapsed)
    else:
        fail(f"OpenAI check failed: {ho.get('detail') or ho}")
        return 2

    # ── Step 1: Ingest ──
    step(1, f"Ingest PDF: {args.pdf}")

    with Timer("ingest") as t:
        r = requests.post(
            f"{base}/books/ingest-repo-pdf",
            data={"title": args.title, "relative_path": args.pdf},
            timeout=600,
        )
    if not r.ok:
        fail(f"Ingest failed: {r.status_code} {r.text[:300]}")
        return 3
    book_id = r.json()["book_id"]
    ok(f"book_id={book_id}, source_id={r.json().get('source_id')}", t.elapsed)

    # ── Step 2: Index ──
    step(2, "Index (chunk + embed)")

    params: dict = {"background": False, "force_restart": True}
    if args.max_pages > 0:
        params["max_pages"] = args.max_pages
    with Timer("index") as t:
        r = requests.post(f"{base}/books/{book_id}/index", params=params, timeout=3600)
    if not r.ok:
        fail(f"Index failed: {r.status_code} {r.text[:300]}")
        return 4
    idx = r.json()
    ok(f"chunks_created={idx.get('chunks_created')}, status={idx.get('index_status')}", t.elapsed)

    # ── Step 3: Generate plan ──
    step(3, "Generate assignment plan (RAG + protocol)")

    with Timer("plan") as t:
        r = requests.post(
            f"{base}/assignments/generate-plan",
            json={
                "book_id": book_id,
                "title": "Smoke Test Assignment",
                "learning_objectives": [
                    "Recall key ideas from the text",
                    "Apply concepts to a new scenario",
                ],
                "scope_query": "main concepts from the text",
                "notes": "Keep it concise for testing.",
            },
            timeout=300,
        )
    if not r.ok:
        fail(f"Plan generation failed: {r.status_code} {r.text[:300]}")
        return 5
    plan_data = r.json()
    assignment_id = plan_data["assignment_id"]
    plan = plan_data.get("plan", {})
    ok(f"assignment_id={assignment_id}, status={plan_data.get('status')}", t.elapsed)
    print(f"  Plan keys: {list(plan.keys()) if isinstance(plan, dict) else type(plan)}")

    # ── Step 4: Approve ──
    step(4, "Approve plan")

    with Timer("approve") as t:
        r = requests.post(
            f"{base}/assignments/{assignment_id}/approve",
            json={"approved": True},
            timeout=30,
        )
    if not r.ok:
        fail(f"Approve failed: {r.status_code} {r.text[:300]}")
        return 6
    ok(f"status={r.json().get('status')}", t.elapsed)

    # Verify via GET
    r2 = requests.get(f"{base}/assignments/{assignment_id}", timeout=30)
    if r2.ok and r2.json().get("status") == "approved":
        ok("GET /assignments/{id} confirms approved")
    else:
        fail(f"GET check failed: {r2.status_code} {r2.text[:200]}")

    # ── Step 5: Generate final assignment ──
    step(5, "Generate final assignment from approved plan")

    with Timer("generate") as t:
        r = requests.post(
            f"{base}/assignments/{assignment_id}/generate",
            json={"scope_query": "main concepts", "notes": ""},
            timeout=300,
        )
    if not r.ok:
        fail(f"Generate failed: {r.status_code} {r.text[:300]}")
        return 7
    gen = r.json()
    assignment = gen.get("assignment", {})
    ok(f"status={gen.get('status')}", t.elapsed)
    print(f"  Title: {assignment.get('title', '?')}")
    print(f"  Stages: {len(assignment.get('instructions', []))}")
    print(f"  Rubric items: {len(assignment.get('rubric', []))}")
    print(f"  AI policy: {assignment.get('ai_policy_summary', '?')[:100]}")

    # Print stages summary
    for s in assignment.get("instructions", []):
        policy = s.get("ai_policy", "?")
        icon = {"Red": "🔴", "Yellow": "🟡", "Green": "🟢"}.get(policy, "⚪")
        print(f"    {icon} {s.get('stage', '?')} — AI: {policy}")

    # ── Summary ──
    wall = time.perf_counter() - wall_start
    print(f"\n{'='*60}")
    print(f"  ALL STEPS PASSED")
    print(f"  Total wall time: {wall:.1f}s")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
