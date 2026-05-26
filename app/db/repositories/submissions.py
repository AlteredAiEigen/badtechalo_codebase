from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.mongo import col, next_seq


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_by_id(sid: int) -> Optional[Dict[str, Any]]:
    return col("submissions").find_one({"id": int(sid)}, {"_id": 0})


def find_existing(assignment_id: int, student_id: str) -> Optional[Dict[str, Any]]:
    return col("submissions").find_one(
        {"assignment_id": int(assignment_id), "student_id": student_id},
        {"_id": 0},
    )


def create(data: Dict[str, Any]) -> Dict[str, Any]:
    sid = next_seq("submissions")
    doc = {"id": sid, "created_at": _now(), "updated_at": _now(), **data}
    col("submissions").insert_one({**doc, "_id": sid})
    return doc


def update(sid: int, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    patch["updated_at"] = _now()
    col("submissions").update_one({"id": int(sid)}, {"$set": patch})
    return get_by_id(sid)
