from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config_env import REPO_ROOT
from app.db.mongo import col


def seed_chapter_from_file(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or (REPO_ROOT / "app" / "data" / "chapter.json")
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    col("chapters").replace_one({"slug": "default"}, {"slug": "default", **data}, upsert=True)
    return data


def load_chapter_data() -> Dict[str, Any]:
    doc = col("chapters").find_one({"slug": "default"}, {"_id": 0, "slug": 0})
    if doc:
        return doc
    return seed_chapter_from_file()


def get_chapter_metadata() -> Dict[str, Any]:
    data = load_chapter_data()
    meta = data.get("metadata") or {}
    return {
        "chapter_number": meta.get("chapternumber"),
        "chapter_name": meta.get("chaptername"),
        "filename": meta.get("filename"),
        "source": "mongodb",
    }


def list_selectable_topics() -> List[Dict[str, Any]]:
    data = load_chapter_data()
    out: List[Dict[str, Any]] = []
    for t in data.get("topics") or []:
        tid = str(t.get("topic_id") or "").strip()
        name = str(t.get("topic_name") or tid or "Topic").strip()
        preview = (t.get("text_content") or "").strip()
        out.append(
            {
                "topic_id": tid,
                "topic_name": name,
                "preview": preview[:280] + ("…" if len(preview) > 280 else ""),
                "has_sub_topics": bool(t.get("sub_topics")),
            }
        )
    return out
