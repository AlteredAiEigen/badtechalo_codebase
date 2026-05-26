from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException

from app.db.repositories import books as books_repo

router = APIRouter(prefix="/books", tags=["books"])


@router.get("/list", response_model=List[dict[str, Any]])
def list_books():
    rows = books_repo.list_all()
    out = []
    for b in rows:
        n = books_repo.chunk_count(b["id"])
        ix = b.get("index_status") or "idle"
        out.append({
            "id": b["id"],
            "title": b.get("title"),
            "pdf_filename": b.get("source_pdf_path", "").split("/")[-1] if b.get("source_pdf_path") else "",
            "source_id": b.get("source_id"),
            "extraction_status": b.get("extraction_status"),
            "index_status": ix,
            "page_count": b.get("page_count"),
            "chunk_count": n,
            "embeddings_ready": n > 0 and ix == "completed",
        })
    return out


@router.get("/{book_id}/index-status", response_model=dict)
def get_index_status(book_id: int):
    book = books_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    return {
        "book_id": book_id,
        "index_status": book.get("index_status") or "idle",
        "index_progress": book.get("index_progress") or {},
        "index_error": book.get("index_error"),
    }
