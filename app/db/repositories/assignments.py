from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.mongo import col, next_seq


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return {}
    out = {k: v for k, v in doc.items() if k != "_id"}
    return out


def get_by_id(aid: int) -> Optional[Dict[str, Any]]:
    return col("assignments").find_one({"id": int(aid)}, {"_id": 0})


def list_all(
    status: Optional[str] = None,
    created_by: Optional[str] = None,
    class_group: Optional[str] = None,
    visible_to_teacher: Optional[str] = None,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if created_by:
        q["created_by"] = created_by
    if class_group:
        q["status"] = "published"
        q["ui_metadata.class_group"] = class_group
    if visible_to_teacher:
        q["$or"] = [
            {"created_by": visible_to_teacher},
            {"visibility": "public", "status": "published"},
        ]
    return list(col("assignments").find(q, {"_id": 0}).sort("id", -1))


def create(data: Dict[str, Any]) -> Dict[str, Any]:
    aid = next_seq("assignments")
    doc = {
        "id": aid,
        "visibility": "private",
        "plan_history": [],
        "last_feedback": None,
        "created_at": _now(),
        "updated_at": _now(),
        **data,
    }
    col("assignments").insert_one({**doc, "_id": aid})
    return doc


def update(aid: int, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    patch["updated_at"] = _now()
    col("assignments").update_one({"id": int(aid)}, {"$set": patch})
    return get_by_id(aid)


def delete(aid: int) -> bool:
    res = col("assignments").delete_one({"id": int(aid)})
    return res.deleted_count > 0
