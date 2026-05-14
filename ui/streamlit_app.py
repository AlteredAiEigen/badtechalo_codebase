"""
Internal testing dashboard — simple flow:
  1. Upload/ingest PDF
  2. Index (chunk + embed)
  3. Generate assignment plan
  4. Approve plan
  5. Generate final assignment

Run:  cd /path/to/backend && streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests
import streamlit as st

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config_env import get_openai_key, load_all_dotenv

load_all_dotenv()

st.set_page_config(page_title="Assignment Platform", layout="wide")
st.title("Assignment Platform")


def base() -> str:
    return st.session_state.get("api_base", "http://127.0.0.1:8000").rstrip("/")


# ── Sidebar: connection + health ──

with st.sidebar:
    st.session_state["api_base"] = st.text_input(
        "API base URL", value="http://127.0.0.1:8000"
    ).rstrip("/")

    try:
        r = requests.get(f"{base()}/", timeout=3)
        st.success(f"API up: {r.json().get('message', 'OK')}")
    except Exception as e:
        st.error(f"API down: {e}")
        st.stop()

    k = get_openai_key()
    if k:
        st.success(f"Key: …{k[-6:]}" if len(k) > 10 else "Key: (short)")
    else:
        st.error("No OpenAI key in app/.env")

    if st.button("Test OpenAI"):
        ho = requests.get(f"{base()}/health/openai", timeout=60).json()
        if ho.get("embeddings_ok") and ho.get("chat_ok"):
            st.success("OpenAI OK")
        else:
            st.error(ho.get("detail") or str(ho))


# ── Step 1: Ingest PDF ──

st.header("Step 1 — Upload PDF")
st.caption("Extracts text + figures from the PDF. No OpenAI calls.")

col1, col2 = st.columns(2)
with col1:
    repo_rel = st.text_input("Repo path", "fecu1dd/fecu101.pdf")
    btitle = st.text_input("Book title", "FECU 101")
    if st.button("Extract from repo", type="primary"):
        with st.spinner("Extracting…"):
            r = requests.post(
                f"{base()}/books/ingest-repo-pdf",
                data={"title": btitle, "relative_path": repo_rel},
                timeout=600,
            )
        if r.ok:
            st.session_state["book_id"] = r.json()["book_id"]
            st.success(f"Done — book_id={r.json()['book_id']}")
        else:
            st.error(r.text)

with col2:
    uf = st.file_uploader("Or upload PDF", type=["pdf"])
    if uf and st.button("Upload & extract"):
        with st.spinner("Uploading…"):
            rr = requests.post(
                f"{base()}/books/upload",
                files={"file": (uf.name, uf.getvalue(), "application/pdf")},
                data={"title": btitle},
                timeout=600,
            )
        if rr.ok:
            st.session_state["book_id"] = rr.json()["book_id"]
            st.success(f"Done — book_id={rr.json()['book_id']}")
        else:
            st.error(rr.text)

st.divider()

# ── Step 2: Index (chunk + embed) ──

st.header("Step 2 — Chunk + Embed")
st.caption("Splits text into chunks (no LLM), then embeds all chunks in one batch OpenAI call. Fast.")

if "book_id" not in st.session_state:
    st.info("Complete Step 1 first.")
else:
    bid = st.session_state["book_id"]
    st.write(f"**book_id:** `{bid}`")

    icol1, icol2 = st.columns(2)
    with icol1:
        max_pg = st.number_input("Max pages (0 = all)", min_value=0, value=0, step=1)
    with icol2:
        force = st.checkbox("Force restart", value=False)

    if st.button("Start indexing", type="primary"):
        params: dict = {"background": False}
        if max_pg > 0:
            params["max_pages"] = int(max_pg)
        if force:
            params["force_restart"] = True

        with st.spinner("Indexing — chunking text + calling OpenAI embeddings…"):
            t0 = time.time()
            r = requests.post(
                f"{base()}/books/{bid}/index",
                params=params,
                timeout=3600,
            )
            elapsed = time.time() - t0

        if r.ok:
            data = r.json()
            st.success(f"Done in {elapsed:.1f}s — {data.get('chunks_created', '?')} chunks created")
            st.json(data)
        else:
            st.error(f"{r.status_code}: {r.text}")

st.divider()

# ── Step 3: Generate assignment plan ──

st.header("Step 3 — Generate Assignment Plan")
st.caption("Uses RAG (retrieves relevant chunks) + GPT-4o to design the assignment following the 6-step instructor protocol.")

if "book_id" not in st.session_state:
    st.info("Complete Steps 1-2 first.")
else:
    at = st.text_input("Assignment title", "Sample Assignment")
    obj = st.text_area("Learning objectives (one per line)", "Students apply concepts from the text.")
    scope = st.text_input("Scope / retrieval query", "opening chapter concepts")
    notes = st.text_area("Teacher notes (optional)", "", height=68)

    if st.button("Generate Plan", type="primary"):
        objectives = [x.strip() for x in obj.split("\n") if x.strip()]
        if not objectives:
            st.error("Add at least one learning objective.")
        elif not scope.strip():
            st.error("Scope cannot be empty.")
        else:
            with st.spinner("Generating plan with GPT-4o…"):
                t0 = time.time()
                pr = requests.post(
                    f"{base()}/assignments/generate-plan",
                    json={
                        "book_id": st.session_state["book_id"],
                        "title": at.strip(),
                        "learning_objectives": objectives,
                        "scope_query": scope.strip(),
                        "notes": notes,
                    },
                    timeout=300,
                )
                elapsed = time.time() - t0

            if pr.ok:
                data = pr.json()
                st.session_state["assignment_id"] = data["assignment_id"]
                st.session_state["plan"] = data.get("plan")
                st.success(f"Plan generated in {elapsed:.1f}s — assignment_id={data['assignment_id']}")
                st.json(data["plan"])
            else:
                st.error(f"{pr.status_code}: {pr.text}")

st.divider()

# ── Step 4: Approve plan ──

st.header("Step 4 — Approve Plan")
st.caption("Review the plan above. Approve it as-is, or edit and re-approve.")

if "assignment_id" not in st.session_state:
    st.info("Generate a plan first (Step 3).")
else:
    aid = st.session_state["assignment_id"]
    st.write(f"**assignment_id:** `{aid}`")

    if "plan" in st.session_state and st.session_state["plan"]:
        with st.expander("Current plan", expanded=True):
            st.json(st.session_state["plan"])

    col_a, col_r = st.columns(2)
    with col_a:
        if st.button("Approve Plan", type="primary"):
            with st.spinner("Approving…"):
                r = requests.post(
                    f"{base()}/assignments/{aid}/approve",
                    json={"approved": True},
                    timeout=30,
                )
            if r.ok:
                st.session_state["approved"] = True
                st.success(f"Plan approved! → {r.json().get('next_step', '')}")
            else:
                st.error(r.text)

    with col_r:
        if st.button("Reject (back to draft)"):
            r = requests.post(
                f"{base()}/assignments/{aid}/approve",
                json={"approved": False},
                timeout=30,
            )
            if r.ok:
                st.session_state.pop("approved", None)
                st.warning("Plan rejected — edit and regenerate if needed.")
            else:
                st.error(r.text)

st.divider()

# ── Step 5: Generate final assignment ──

st.header("Step 5 — Generate Final Assignment")
st.caption("Takes the approved plan and generates the complete assignment: instructions, rubric, AI policy per stage, deliverables.")

if "assignment_id" not in st.session_state:
    st.info("Complete Steps 3-4 first.")
elif not st.session_state.get("approved"):
    st.warning("Approve the plan first (Step 4).")
else:
    aid = st.session_state["assignment_id"]
    extra_notes = st.text_area("Additional notes for generation (optional)", "", height=68, key="gen_notes")

    if st.button("Generate Assignment", type="primary"):
        with st.spinner("Generating full assignment with GPT-4o…"):
            t0 = time.time()
            r = requests.post(
                f"{base()}/assignments/{aid}/generate",
                json={
                    "scope_query": st.session_state.get("scope_query", ""),
                    "notes": extra_notes,
                },
                timeout=300,
            )
            elapsed = time.time() - t0

        if r.ok:
            data = r.json()
            st.success(f"Assignment generated in {elapsed:.1f}s!")
            assignment = data.get("assignment", {})

            st.subheader(assignment.get("title", "Assignment"))
            st.write(assignment.get("description", ""))

            if assignment.get("instructions"):
                st.subheader("Stages")
                for stage in assignment["instructions"]:
                    color = {"Red": "🔴", "Yellow": "🟡", "Green": "🟢"}.get(
                        stage.get("ai_policy", ""), "⚪"
                    )
                    with st.expander(f"{color} {stage.get('stage', 'Stage')} — AI: {stage.get('ai_policy', '?')}"):
                        st.write(stage.get("instructions", ""))
                        st.caption(f"AI guidance: {stage.get('ai_guidance', '')}")
                        st.caption(f"Deliverable: {stage.get('deliverable', '')}")

            if assignment.get("rubric"):
                st.subheader("Rubric")
                for item in assignment["rubric"]:
                    st.write(f"**{item.get('criterion', '')}** ({item.get('weight', '')}): {item.get('description', '')}")

            if assignment.get("ai_policy_summary"):
                st.subheader("AI Policy Summary")
                st.info(assignment["ai_policy_summary"])

            with st.expander("Raw JSON"):
                st.json(data)
        else:
            st.error(f"{r.status_code}: {r.text}")
