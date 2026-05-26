from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.mongo import col, next_seq


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_user(email: str, password_hash: str, role: str, full_name: str) -> Dict[str, Any]:
    existing = col("users").find_one({"email": email.lower()})
    if existing:
        raise ValueError("Email already registered")
    uid = next_seq("users")
    doc = {
        "id": uid,
        "email": email.lower(),
        "password_hash": password_hash,
        "role": role,
        "full_name": full_name,
        "avatar_url": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    col("users").insert_one({**doc, "_id": uid})
    return doc


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    return col("users").find_one({"email": email.lower()}, {"_id": 0})


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    return col("users").find_one({"id": int(user_id)}, {"_id": 0})


def public_user(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "email": doc["email"],
        "role": doc["role"],
        "full_name": doc.get("full_name"),
        "avatar_url": doc.get("avatar_url"),
    }
