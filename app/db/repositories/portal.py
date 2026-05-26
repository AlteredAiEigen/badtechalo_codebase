from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.db.mongo import col, next_seq


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    out = {k: v for k, v in doc.items() if k != "_id"}
    if "id" not in out and "_id" in doc:
        out["id"] = str(doc["_id"])
    return out


def list_docs(collection: str, query: Optional[Dict[str, Any]] = None, limit: int = 500) -> List[Dict[str, Any]]:
    q = query or {}
    return [_strip(d) for d in col(collection).find(q).sort("created_at", -1).limit(limit)]


def get_doc(collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
    try:
        oid = ObjectId(doc_id)
        doc = col(collection).find_one({"_id": oid})
    except Exception:
        doc = col(collection).find_one({"id": doc_id})
    return _strip(doc)


def insert_doc(collection: str, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = {**data, "created_at": _now(), "updated_at": _now()}
    if "id" not in doc and collection not in ("users", "assignments", "submissions", "books", "chunks"):
        doc["id"] = str(ObjectId())
    res = col(collection).insert_one(doc)
    doc["_id"] = res.inserted_id
    return _strip(doc) or doc


def update_doc(collection: str, doc_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    patch["updated_at"] = _now()
    try:
        oid = ObjectId(doc_id)
        col(collection).update_one({"_id": oid}, {"$set": patch})
        return get_doc(collection, doc_id)
    except Exception:
        col(collection).update_one({"id": doc_id}, {"$set": patch})
        return get_doc(collection, doc_id)


def delete_doc(collection: str, doc_id: str) -> bool:
    try:
        oid = ObjectId(doc_id)
        res = col(collection).delete_one({"_id": oid})
    except Exception:
        res = col(collection).delete_one({"id": doc_id})
    return res.deleted_count > 0
