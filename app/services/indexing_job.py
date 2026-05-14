"""Background book indexing (chunk + embed) with status on Book row."""

from __future__ import annotations

import traceback

from openai import OpenAIError
from sqlalchemy.orm import Session

from app.config_env import load_all_dotenv
from app.db.database import SessionLocal
from app.db.models import Book
from app.services.rag import process_book_chunks


def _fail_index(book_id: int, err: str) -> None:
    db: Session = SessionLocal()
    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if book:
            book.index_status = "failed"
            book.index_error = err[:8000]
            book.index_progress = {
                **(book.index_progress or {}),
                "phase": "failed",
                "message": "Indexing failed. See index_error.",
            }
            db.add(book)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def run_book_indexing(book_id: int, max_pages: int | None = None) -> None:
    """Run in FastAPI BackgroundTasks; uses its own DB session."""
    load_all_dotenv()
    db: Session = SessionLocal()
    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if not book:
            return

        book.index_status = "running"
        book.index_error = None
        book.index_progress = {
            "phase": "starting",
            "message": "Starting chunk + embed pipeline…",
        }
        db.add(book)
        db.commit()

        num = process_book_chunks(db, book, report_progress=True, max_pages=max_pages)

        db.refresh(book)
        book.index_status = "completed"
        book.index_error = None
        book.index_progress = {
            **(book.index_progress or {}),
            "phase": "completed",
            "chunks_created": num,
            "message": f"Done. {num} chunk(s) stored with embeddings.",
        }
        db.add(book)
        db.commit()
    except OpenAIError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        _fail_index(book_id, f"OpenAI error: {exc}")
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:
            pass
        _fail_index(book_id, f"{exc}\n{traceback.format_exc()}")
    finally:
        db.close()
