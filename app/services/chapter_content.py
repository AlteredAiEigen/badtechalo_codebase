"""Load manually curated chapter JSON and build RAG-style context for assignment design."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_APP_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_CHAPTER_PATH = _APP_DIR / "data" / "chapter.json"


def chapter_json_path() -> Path:
    raw = (os.getenv("CHAPTER_JSON_PATH") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (_APP_DIR / p).resolve()
    return _DEFAULT_CHAPTER_PATH


@lru_cache(maxsize=1)
def load_chapter_data() -> Dict[str, Any]:
    path = chapter_json_path()
    if not path.is_file():
        raise FileNotFoundError(f"Chapter data not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def clear_chapter_cache() -> None:
    load_chapter_data.cache_clear()


def get_chapter_metadata() -> Dict[str, Any]:
    data = load_chapter_data()
    meta = data.get("metadata") or {}
    return {
        "chapter_number": meta.get("chapternumber"),
        "chapter_name": meta.get("chaptername"),
        "filename": meta.get("filename"),
        "source_path": str(chapter_json_path()),
    }


def list_selectable_topics() -> List[Dict[str, Any]]:
    """Top-level topics only (teacher picks whole chapter or subset of these)."""
    data = load_chapter_data()
    out: List[Dict[str, Any]] = []
    for t in data.get("topics") or []:
        tid = str(t.get("topic_id") or "").strip()
        name = str(t.get("topic_name") or tid or "Topic").strip()
        preview = (t.get("text_content") or "").strip()
        if not preview and t.get("sub_topics"):
            preview = _first_text_from_subtopics(t.get("sub_topics") or [])
        out.append(
            {
                "topic_id": tid,
                "topic_name": name,
                "preview": preview[:280] + ("…" if len(preview) > 280 else ""),
                "has_sub_topics": bool(t.get("sub_topics")),
            }
        )
    return out


def _first_text_from_subtopics(sub_topics: List[Dict[str, Any]]) -> str:
    for st in sub_topics:
        text = (st.get("text_content") or st.get("description") or "").strip()
        if text:
            return text
        nested = st.get("sub_topics") or []
        if nested:
            found = _first_text_from_subtopics(nested)
            if found:
                return found
    return ""


def _append_subtopic_lines(parts: List[str], sub_topics: List[Dict[str, Any]], depth: int = 0) -> None:
    indent = "  " * depth
    for st in sub_topics or []:
        stype = str(st.get("type") or "section").strip()
        name = str(st.get("name") or "").strip()
        desc = str(st.get("description") or "").strip()
        text = str(st.get("text_content") or "").strip()
        header = f"{indent}[{stype}] {name}".strip()
        if header and header != f"{indent}[{stype}]":
            parts.append(header)
        if desc:
            parts.append(f"{indent}{desc}")
        if text:
            parts.append(f"{indent}{text}")
        nested = st.get("sub_topics") or []
        if nested:
            _append_subtopic_lines(parts, nested, depth + 1)


def _topic_block(topic: Dict[str, Any]) -> str:
    tid = str(topic.get("topic_id") or "").strip()
    name = str(topic.get("topic_name") or tid).strip()
    parts = [f"## Topic {tid}: {name}"]
    main_text = (topic.get("text_content") or "").strip()
    if main_text:
        parts.append(main_text)
    sub_topics = topic.get("sub_topics") or []
    if sub_topics:
        parts.append("### Sections")
        _append_subtopic_lines(parts, sub_topics, depth=0)
    return "\n\n".join(parts)


def build_chapter_context(
    topic_ids: Optional[List[str]] = None,
    *,
    whole_chapter: bool = False,
    max_chars: int = 120_000,
) -> tuple[str, List[str], str]:
    """
    Build context text from chapter.json.

    Returns (context_text, selected_topic_ids, scope_label).
    """
    data = load_chapter_data()
    topics: List[Dict[str, Any]] = list(data.get("topics") or [])
    meta = data.get("metadata") or {}
    chapter_label = meta.get("chaptername") or f"Chapter {meta.get('chapternumber', '')}"

    if whole_chapter or not topic_ids:
        selected = topics
        ids = [str(t.get("topic_id") or "") for t in selected if t.get("topic_id")]
        scope_label = f"Whole chapter — {chapter_label}"
    else:
        want = {str(x).strip() for x in topic_ids if str(x).strip()}
        selected = [t for t in topics if str(t.get("topic_id") or "").strip() in want]
        if not selected:
            known = [str(t.get("topic_id")) for t in topics]
            raise ValueError(f"No topics matched ids {sorted(want)}. Known ids: {known}")
        ids = [str(t.get("topic_id") or "") for t in selected]
        names = [str(t.get("topic_name") or i) for t, i in zip(selected, ids)]
        scope_label = f"Selected topics ({', '.join(names)}) — {chapter_label}"

    blocks = [f"# {chapter_label}", f"Source: {meta.get('filename', 'chapter.json')}"]
    for t in selected:
        blocks.append(_topic_block(t))

    context = "\n\n---\n\n".join(blocks)
    if len(context) > max_chars:
        context = context[:max_chars] + "\n\n[…truncated for model context limit…]"

    return context, ids, scope_label


def chapter_context_for_scope(
    *,
    whole_chapter: bool = False,
    topic_ids: Optional[List[str]] = None,
    scope_query: str = "",
) -> tuple[str, List[str], str]:
    """
    Prefer explicit chapter selection; fall back to whole chapter when nothing selected.
    scope_query is kept as a human label suffix for the teacher's notes in prompts.
    """
    use_whole = whole_chapter or not (topic_ids or [])
    ctx, ids, label = build_chapter_context(topic_ids=topic_ids, whole_chapter=use_whole)
    if scope_query.strip():
        label = f"{label} · Teacher scope note: {scope_query.strip()}"
    return ctx, ids, label
