from fastapi import APIRouter, HTTPException

from app.db.repositories import books as books_repo
from app.db.repositories import chapters as chapters_repo

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/chapter")
def get_chapter_outline():
    """Metadata and top-level topics from MongoDB (seeded from chapter.json)."""
    try:
        chapters_repo.load_chapter_data()
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc

    return {
        "metadata": chapters_repo.get_chapter_metadata(),
        "topics": chapters_repo.list_selectable_topics(),
    }


@router.get("/book")
def get_canonical_book():
    """The single textbook entry teachers use for Science assignments."""
    try:
        chapters_repo.load_chapter_data()
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    book = books_repo.get_canonical_book()
    if not book:
        raise HTTPException(
            404,
            "Canonical chapter book not seeded. Run backend/scripts/seed_mongo.py.",
        )
    meta = chapters_repo.get_chapter_metadata()
    return {
        "id": book["id"],
        "title": book.get("title"),
        "source_id": book.get("source_id"),
        "filename": meta.get("filename"),
        "chapter_number": meta.get("chapter_number"),
        "chapter_name": meta.get("chapter_name"),
        "content_source": "chapter_json",
    }
