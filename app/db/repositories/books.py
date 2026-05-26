from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.mongo import col, next_seq

CANONICAL_SOURCE_ID = "fec0102"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_canonical_book() -> Optional[Dict[str, Any]]:
    return col("books").find_one({"source_id": CANONICAL_SOURCE_ID}, {"_id": 0})


def get_canonical_book_id() -> int:
    book = get_canonical_book()
    if not book:
        raise RuntimeError("Canonical chapter book is not seeded. Run scripts/seed_mongo.py.")
    return int(book["id"])


def get_by_id(book_id: int) -> Optional[Dict[str, Any]]:
    return col("books").find_one({"id": int(book_id)}, {"_id": 0})


def list_all() -> List[Dict[str, Any]]:
    book = get_canonical_book()
    return [book] if book else []


def seed_canonical_book_from_chapter(chapter_data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure exactly one book exists, mapped to chapter.json metadata."""
    meta = chapter_data.get("metadata") or {}
    filename = str(meta.get("filename") or "fec0102.pdf")
    title = str(meta.get("chaptername") or "Diversity in the Living World")
    chapter_number = meta.get("chapternumber")

    col("books").delete_many({"source_id": {"$ne": CANONICAL_SOURCE_ID}})
    col("chunks").delete_many({})

    existing = get_canonical_book()
    doc = {
        "id": existing["id"] if existing else 1,
        "source_id": CANONICAL_SOURCE_ID,
        "title": title,
        "source_pdf_path": f"app/data/{filename}",
        "extraction_status": "completed",
        "index_status": "completed",
        "page_count": None,
        "chapter_number": chapter_number,
        "content_source": "chapter_json",
        "updated_at": _now(),
    }
    if existing:
        col("books").update_one({"id": existing["id"]}, {"$set": doc})
        return get_by_id(existing["id"]) or doc

    doc["created_at"] = _now()
    col("books").delete_many({})
    col("books").insert_one({**doc, "_id": doc["id"]})
    col("counters").update_one({"_id": "books"}, {"$set": {"seq": doc["id"]}}, upsert=True)
    return doc


def assert_canonical_book_id(book_id: int) -> None:
    canonical_id = get_canonical_book_id()
    if int(book_id) != canonical_id:
        raise ValueError(
            f"Only the chapter.json textbook is supported (book_id={canonical_id}). "
            f"Received book_id={book_id}."
        )


def upsert_by_source_id(source_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    existing = col("books").find_one({"source_id": source_id}, {"_id": 0})
    if existing:
        col("books").update_one({"id": existing["id"]}, {"$set": {**data, "updated_at": _now()}})
        return get_by_id(existing["id"]) or existing
    bid = next_seq("books")
    doc = {"id": bid, "source_id": source_id, "created_at": _now(), "updated_at": _now(), **data}
    col("books").insert_one({**doc, "_id": bid})
    return doc


def chunk_count(book_id: int) -> int:
    return col("chunks").count_documents({"book_id": int(book_id)})


def list_chunks(book_id: int) -> List[Dict[str, Any]]:
    return list(col("chunks").find({"book_id": int(book_id)}, {"_id": 0}))


def replace_chunks(book_id: int, chunks: List[Dict[str, Any]]) -> None:
    col("chunks").delete_many({"book_id": int(book_id)})
    if not chunks:
        return
    for i, c in enumerate(chunks):
        cid = next_seq("chunks")
        doc = {"id": cid, "book_id": int(book_id), **c}
        col("chunks").insert_one({**doc, "_id": cid})


def get_chunks_by_ids(book_id: int, chunk_ids: List[int]) -> List[Dict[str, Any]]:
    rows = list(
        col("chunks").find({"book_id": int(book_id), "id": {"$in": [int(x) for x in chunk_ids]}}, {"_id": 0})
    )
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]
