import json

from fastapi import APIRouter, HTTPException

from app.services.chapter_content import (
    get_chapter_metadata,
    list_selectable_topics,
    load_chapter_data,
)

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/chapter")
def get_chapter_outline():
    """Metadata and top-level topics from manually curated chapter.json."""
    try:
        load_chapter_data()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Invalid chapter JSON: {exc}") from exc

    return {
        "metadata": get_chapter_metadata(),
        "topics": list_selectable_topics(),
    }
