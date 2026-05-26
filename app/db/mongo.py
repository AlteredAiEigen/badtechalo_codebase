"""MongoDB Atlas connection for BadteChalo."""

from __future__ import annotations

from typing import Generator

from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

from app.config_env import get_mongodb_db_name, get_mongodb_uri

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client  # noqa: PLW0603
    uri = get_mongodb_uri()
    if not uri:
        raise RuntimeError("MONGODB_URI is not configured in backend/.env")
    if _client is None:
        _client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    return _client


def get_database() -> Database:
    return get_client()[get_mongodb_db_name()]


def col(name: str) -> Collection:
    return get_database()[name]


def next_seq(name: str) -> int:
    """Auto-increment integer ids (compatible with existing frontend int ids)."""
    doc = col("counters").find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


def get_mongo() -> Generator[Database, None, None]:
    yield get_database()


def ping_mongo() -> bool:
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False
