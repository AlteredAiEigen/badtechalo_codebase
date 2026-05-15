"""
Assignment Platform — Teacher + Student UI
  cd /path/to/backend && streamlit run ui/streamlit_app.py
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


# ── Sidebar ──

with st.sidebar:
    st.session_state["api_base"] = st.text_input("API URL", value="http://127.0.0.1:8000").rstrip("/")
    try:
        r = requests.get(f"{base()}/", timeout=3)
        st.success(f"API: {r.json().get('message', 'OK')}")
    except Exception as e:
        st.error(f"API down: {e}")
        st.stop()

    k = get_openai_key()
    if k:
        st.success(f"Key: …{k[-6:]}" if len(k) > 10 else "Key: (short)")
    else:
        st.error("No OpenAI key in app/.env")

    if st.button("Test OpenAI"):
        ho = requests.get(f"{base()}/health/openai", timeout=120).json()
        if ho.get("embeddings_ok") and ho.get("chat_ok"):
            st.success("OpenAI OK")
        else:
            st.error(ho.get("detail") or str(ho))
            if ho.get("how_to_fix_connection"):
                st.warning(ho["how_to_fix_connection"])
            if ho.get("how_to_fix"):
                st.info(ho["how_to_fix"])


# ── Tabs ──

tab_teacher, tab_student = st.tabs(["Teacher — Design Assignment", "Student — Do Assignment"])


# ============================================================
# TEACHER TAB
# ============================================================

with tab_teacher:

    st.subheader("Select book")
    st.caption(
        "Rows show **database ID**, **PDF file name** (from the file you ingested), **title** (the name you typed at ingest), "
        "then how many **chunks/embeddings** exist for RAG. The title is not taken from chunk text."
    )

    books_rows: list = []
    books_list_error: str | None = None
    try:
        br = requests.get(f"{base()}/books/list", timeout=10)
        if br.ok:
            raw = br.json()
            books_rows = raw if isinstance(raw, list) else []
            if not isinstance(raw, list):
                books_list_error = "Unexpected /books/list response (not a JSON list)."
        else:
            books_list_error = f"HTTP {br.status_code}: {br.text[:200]}"
    except Exception as ex:
        books_list_error = str(ex)
    if books_list_error:
        st.warning(books_list_error)

    def _book_row_label(b: dict) -> str:
        bid = int(b["id"])
        pdf = str(b.get("pdf_filename") or "").strip() or str(b.get("source_id") or "?")
        title = str(b.get("title") or "").replace("\n", " ").strip() or "(no ingest title)"
        if len(title) > 40:
            title = title[:39] + "…"
        n = int(b.get("chunk_count") or 0)
        ix = str(b.get("index_status") or "idle")
        if n > 0:
            emb = f"{n} chunks"
        else:
            emb = "0 chunks"
        return f"ID {bid}  |  {pdf}  |  title: {title}  |  {emb}  |  index: {ix}"

    c_refresh, c_meta = st.columns([1, 4])
    with c_refresh:
        if st.button("Refresh list", key="refresh_books_list"):
            st.rerun()
    if books_rows:
        ids_all = [int(x["id"]) for x in books_rows]
        with c_meta:
            st.caption(f"**{len(books_rows)}** book(s) from API · highest ID **{max(ids_all)}**")

    if books_rows:
        n_rows = len(books_rows)
        cur_bid = st.session_state.get("book_id")
        cur_ids = [int(x["id"]) for x in books_rows]
        default_ix = cur_ids.index(int(cur_bid)) if cur_bid is not None and int(cur_bid) in cur_ids else 0
        default_ix = min(max(default_ix, 0), n_rows - 1)

        pick_ix = st.selectbox(
            "Books in backend (ID · PDF filename · ingest title · chunks)",
            options=list(range(n_rows)),
            index=default_ix,
            format_func=lambda i: _book_row_label(books_rows[i]),
            key="teacher_book_pick_ix",
        )
        picked_id = int(books_rows[pick_ix]["id"])
        if st.button("Use selected book as current book_id", type="primary", key="teacher_apply_book"):
            st.session_state["book_id"] = picked_id
            st.success(f"Using book_id **{picked_id}** — Step 2 if not indexed; Step 3 when embeddings exist.")
        st.caption(f"Current session `book_id`: `{st.session_state.get('book_id', '—')}`")

        st.divider()
        st.caption("Or set `book_id` by number:")
        ex_bid = st.number_input(
            "book_id (manual)",
            min_value=1,
            value=int(picked_id),
            step=1,
            key="existing_book_id_input",
        )
        if st.button("Use this book_id", key="use_existing_book_manual"):
            st.session_state["book_id"] = int(ex_bid)
            st.success(f"Set book_id={ex_bid}.")
    else:
        st.info("No books returned from the API yet — use Step 1 below to ingest a PDF (then refresh this page).")
        st.divider()
        ex_bid = st.number_input("book_id (manual only)", min_value=1, value=1, step=1, key="existing_book_id_input")
        if st.button("Use this book_id", key="use_existing_book_manual"):
            st.session_state["book_id"] = int(ex_bid)
            st.success(f"Set book_id={ex_bid}.")

    st.divider()

    # Step 1: Ingest
    st.header("Step 1 — Upload PDF")
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

    # Step 2: Index
    st.header("Step 2 — Chunk + Embed")
    if "book_id" not in st.session_state:
        st.info("Set book_id via **Select book** above or Step 1.")
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
            with st.spinner("Indexing…"):
                t0 = time.time()
                r = requests.post(f"{base()}/books/{bid}/index", params=params, timeout=3600)
                elapsed = time.time() - t0
            if r.ok:
                st.success(f"Done in {elapsed:.1f}s — {r.json().get('chunks_created', '?')} chunks")
            else:
                st.error(f"{r.status_code}: {r.text}")

    st.divider()

    # Step 3: Generate plan
    st.header("Step 3 — Generate Plan")
    if "book_id" not in st.session_state:
        st.info("Set book_id (Step 1, or existing book expander). Step 2 only if the book is not indexed yet.")
    else:
        at = st.text_input("Assignment title", "Sample Assignment")
        obj = st.text_area("Learning objectives (one per line)", "Students apply concepts from the text.")
        scope = st.text_input("Scope / retrieval query", "opening chapter concepts")
        notes = st.text_area("Teacher notes", "", height=68)
        if st.button("Generate Plan", type="primary"):
            objectives = [x.strip() for x in obj.split("\n") if x.strip()]
            if not objectives:
                st.error("Add at least one learning objective.")
            elif not scope.strip():
                st.error("Scope cannot be empty.")
            else:
                with st.spinner("Generating plan…"):
                    t0 = time.time()
                    pr = requests.post(f"{base()}/assignments/generate-plan", json={
                        "book_id": st.session_state["book_id"],
                        "title": at.strip(), "learning_objectives": objectives,
                        "scope_query": scope.strip(), "notes": notes,
                    }, timeout=300)
                    elapsed = time.time() - t0
                if pr.ok:
                    data = pr.json()
                    st.session_state["assignment_id"] = data["assignment_id"]
                    st.session_state["plan"] = data.get("plan")
                    st.session_state["plan_scope_query"] = scope.strip()
                    st.success(f"Plan generated in {elapsed:.1f}s — assignment_id={data['assignment_id']}")
                    st.json(data["plan"])
                else:
                    st.error(f"{pr.status_code}: {pr.text}")

    st.divider()

    # Step 4: Approve
    st.header("Step 4 — Approve Plan")
    if "assignment_id" not in st.session_state:
        st.info("Generate a plan first.")
    else:
        aid = st.session_state["assignment_id"]
        if "plan" in st.session_state and st.session_state["plan"]:
            with st.expander("Current plan", expanded=True):
                st.json(st.session_state["plan"])
        col_a, col_r = st.columns(2)
        with col_a:
            if st.button("Approve", type="primary"):
                r = requests.post(f"{base()}/assignments/{aid}/approve", json={"approved": True}, timeout=30)
                if r.ok:
                    st.session_state["approved"] = True
                    st.success("Plan approved!")
                else:
                    st.error(r.text)
        with col_r:
            if st.button("Reject"):
                r = requests.post(f"{base()}/assignments/{aid}/approve", json={"approved": False}, timeout=30)
                if r.ok:
                    st.session_state.pop("approved", None)
                    st.warning("Rejected — regenerate if needed.")
                else:
                    st.error(r.text)

    st.divider()

    # Step 5: Generate final assignment
    st.header("Step 5 — Generate Final Assignment")
    if "assignment_id" not in st.session_state:
        st.info("Complete Steps 3-4 first.")
    elif not st.session_state.get("approved"):
        st.warning("Approve the plan first.")
    else:
        aid = st.session_state["assignment_id"]
        extra_notes = st.text_area("Extra notes for generation", "", height=68, key="gen_notes")
        rerag = st.checkbox(
            "Re-run RAG retrieval (embeds scope query again). Leave off to reuse the same chunks as the plan.",
            value=False,
            key="rerag_final",
        )
        if st.button("Generate Assignment", type="primary"):
            with st.spinner("Generating…"):
                t0 = time.time()
                gen_body: dict = {"notes": extra_notes}
                if rerag:
                    gen_body["scope_query"] = st.session_state.get("plan_scope_query") or ""
                r = requests.post(f"{base()}/assignments/{aid}/generate", json=gen_body, timeout=300)
                elapsed = time.time() - t0
            if r.ok:
                data = r.json()
                st.success(f"Generated in {elapsed:.1f}s!")
                a = data.get("assignment", {})
                st.subheader(a.get("title", "Assignment"))
                st.write(a.get("description", ""))
                if a.get("platform_notice"):
                    st.warning(a["platform_notice"])
                gs = a.get("grading_summary", {})
                if gs:
                    st.info(f"**Grading:** Process {gs.get('process_total_percentage', '?')}% / Final {gs.get('final_output_total_percentage', '?')}%")
                stages = a.get("stages") or []
                for stage in stages:
                    policy = stage.get("ai_policy", "?")
                    icon = {"Red": "🔴", "Yellow": "🟡", "Green": "🟢"}.get(policy, "⚪")
                    cp = " 📋" if stage.get("is_checkpoint") else ""
                    fp = " ⚡" if stage.get("is_friction_point") else ""
                    with st.expander(f"{icon} Stage {stage.get('stage_number', '?')}: {stage.get('stage_name', '')} — {policy}{cp}{fp}"):
                        st.write(stage.get("instructions", ""))
                        if stage.get("ai_guidance"):
                            st.markdown(f"**AI guidance:** {stage['ai_guidance']}")
                        if stage.get("checkpoint_deliverable"):
                            st.markdown(f"**Submit:** {stage['checkpoint_deliverable']}")
                        if stage.get("friction_prompt"):
                            st.markdown(f"**Justify:** _{stage['friction_prompt']}_")
                if a.get("rubric"):
                    st.subheader("Rubric")
                    for item in a["rubric"]:
                        cat = f" [{item.get('category', '')}]" if item.get("category") else ""
                        w = item.get("weight_percentage") or item.get("weight", "?")
                        st.write(f"**{item.get('criterion', '')}** — {w}%{cat}: {item.get('description', '')}")
                if a.get("ai_policy_summary"):
                    st.info(a["ai_policy_summary"])
                with st.expander("Raw JSON"):
                    st.json(data)
            else:
                st.error(f"{r.status_code}: {r.text}")


# ============================================================
# STUDENT TAB
# ============================================================

with tab_student:

    st.header("Do Your Assignment")
    st.caption("Work through each stage. Submit your checkpoint at each stage before moving on.")

    # --- Start / resume ---
    st.subheader("Start or Resume")
    s_aid = st.number_input("Assignment ID", min_value=1, value=st.session_state.get("assignment_id", 1), step=1, key="s_aid")
    s_name = st.text_input("Your name / student ID", "student_1", key="s_name")

    if st.button("Start Assignment", key="start_btn"):
        r = requests.post(f"{base()}/submissions/start", json={
            "assignment_id": int(s_aid), "student_id": s_name,
        }, timeout=30)
        if r.ok:
            d = r.json()
            st.session_state["sub_id"] = d["submission_id"]
            st.success(f"{d.get('message', 'Started')} — submission_id={d['submission_id']}")
        else:
            st.error(f"{r.status_code}: {r.text}")

    if "sub_id" not in st.session_state:
        st.info("Enter the assignment ID and your name above, then click Start.")
    else:
        sub_id = st.session_state["sub_id"]

        # Fetch current state
        sr = requests.get(f"{base()}/submissions/{sub_id}", timeout=30)
        if not sr.ok:
            st.error(f"Could not load submission: {sr.text}")
        else:
            sub = sr.json()
            total = sub["total_stages"]
            current_idx = sub["current_stage_index"]
            current_stage = sub.get("current_stage")
            all_stages = sub.get("all_stages") or []

            st.divider()

            # --- Progress bar ---
            if total > 0:
                frac = min(1.0, current_idx / total)
                st.progress(frac, text=f"Stage {min(current_idx + 1, total)} of {total} — {sub['status']}")

            # --- Show all stages with status ---
            st.subheader("Assignment Stages")
            for i, stage in enumerate(all_stages):
                policy = stage.get("ai_policy", "?")
                icon = {"Red": "🔴", "Yellow": "🟡", "Green": "🟢"}.get(policy, "⚪")
                if i < current_idx:
                    status_icon = "✅"
                elif i == current_idx:
                    status_icon = "👉"
                else:
                    status_icon = "🔒"

                name = stage.get("stage_name", f"Stage {i+1}")
                fp = " ⚡" if stage.get("is_friction_point") else ""
                label = f"{status_icon} {icon} Stage {stage.get('stage_number', i+1)}: {name} — AI: {policy}{fp}"

                if i < current_idx:
                    with st.expander(label):
                        st.success("Completed")
                        st.caption(stage.get("instructions", ""))
                elif i == current_idx:
                    with st.expander(label, expanded=True):
                        st.markdown(f"**Instructions:** {stage.get('instructions', '')}")

                        if stage.get("ai_guidance"):
                            if policy == "Red":
                                st.error(f"🔴 AI NOT PERMITTED: {stage['ai_guidance']}")
                            elif policy == "Yellow":
                                st.warning(f"🟡 AI allowed with structure: {stage['ai_guidance']}")
                            else:
                                st.info(f"🟢 AI encouraged: {stage['ai_guidance']}")

                        if stage.get("checkpoint_deliverable"):
                            st.markdown(f"**What to submit:** {stage['checkpoint_deliverable']}")

                        if stage.get("brain_first_requirement"):
                            st.caption(f"Brain-first: {stage['brain_first_requirement']}")
                else:
                    st.markdown(f"{label}")

            st.divider()

            # --- Current stage work area ---
            if sub["status"] == "submitted":
                st.success("🎉 Assignment complete! All stages submitted.")

                with st.expander("View your process log"):
                    lr = requests.get(f"{base()}/submissions/{sub_id}/log", timeout=30)
                    if lr.ok:
                        log = lr.json().get("log", [])
                        for entry in log:
                            et = entry.get("event_type", "")
                            ts = entry.get("timestamp", "")[:19]
                            content = entry.get("content", {})
                            if et == "checkpoint_submit":
                                st.markdown(f"**{ts}** — 📋 Checkpoint: {content.get('stage_name', '')}")
                                st.caption(f"Words: {content.get('word_count', '?')}")
                            elif et == "ai_interaction":
                                st.markdown(f"**{ts}** — 🤖 AI help at: {content.get('stage_name', '')}")
                                st.caption(f"AI role: {content.get('ai_role', '?')}")
                            elif et == "assignment_started":
                                st.markdown(f"**{ts}** — 🚀 Started")
                            else:
                                st.markdown(f"**{ts}** — {et}")

            elif current_stage:
                stage = current_stage
                policy = (stage.get("ai_policy") or "Red").strip()
                stage_name = stage.get("stage_name", f"Stage {current_idx + 1}")

                st.subheader(f"Working on: {stage_name}")

                student_work = st.text_area(
                    "Your work for this stage",
                    height=200,
                    key=f"work_{sub_id}_{current_idx}",
                    placeholder="Write your work here…",
                )

                friction_answer = None
                if stage.get("is_friction_point") and stage.get("friction_prompt"):
                    st.markdown(f"**⚡ Justification required:** _{stage['friction_prompt']}_")
                    friction_answer = st.text_area(
                        "Your justification",
                        height=100,
                        key=f"friction_{sub_id}_{current_idx}",
                        placeholder="Explain your reasoning…",
                    )

                col_submit, col_ai = st.columns(2)

                with col_submit:
                    if st.button("Submit Checkpoint", type="primary", key=f"submit_{current_idx}"):
                        payload = {"student_work": student_work}
                        if friction_answer:
                            payload["friction_answer"] = friction_answer
                        r = requests.post(
                            f"{base()}/submissions/{sub_id}/checkpoint",
                            json=payload,
                            timeout=60,
                        )
                        if r.ok:
                            d = r.json()
                            if d.get("all_done"):
                                st.success("🎉 All stages complete! Assignment submitted.")
                            else:
                                st.success(f"✅ '{d.get('completed_stage')}' submitted! Next: {d.get('next_stage')}")
                            st.rerun()
                        else:
                            try:
                                detail = r.json().get("detail", r.text)
                            except Exception:
                                detail = r.text
                            st.error(f"Could not submit: {detail}")

                with col_ai:
                    if policy == "Red":
                        st.button("🤖 Ask AI", disabled=True, key=f"ai_{current_idx}",
                                  help="AI is not permitted at this stage.")
                    else:
                        ai_role = stage.get("ai_role", "learning coach")
                        if st.button(f"🤖 Ask AI ({ai_role})", key=f"ai_{current_idx}"):
                            if not student_work or len(student_work.strip()) < 30:
                                st.warning("Brain-first: write your own work first (at least a few sentences) before asking AI.")
                            else:
                                with st.spinner(f"Asking AI ({ai_role})…"):
                                    ar = requests.post(
                                        f"{base()}/submissions/{sub_id}/ai-help",
                                        json={"student_attempt": student_work},
                                        timeout=120,
                                    )
                                if ar.ok:
                                    ai_data = ar.json()
                                    st.markdown(f"**🤖 {ai_data.get('ai_role', 'AI')} says:**")
                                    st.info(ai_data.get("response", ""))
                                    st.caption(ai_data.get("reminder", ""))
                                else:
                                    try:
                                        detail = ar.json().get("detail", ar.text)
                                        if isinstance(detail, dict):
                                            detail = detail.get("error") or detail.get("reason") or str(detail)
                                    except Exception:
                                        detail = ar.text
                                    st.error(f"AI help unavailable: {detail}")
