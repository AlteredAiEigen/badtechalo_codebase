import shutil
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from openai import OpenAIError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config_env import REPO_ROOT, get_openai_key, load_all_dotenv
from app.db.database import get_db
from app.db.models import Book, Chunk
from app.openai_http import http_exception_from_openai
from app.services.indexing_job import run_book_indexing
from app.services.ingestion import ingest_book
from app.services.rag import process_book_chunks

router = APIRouter(prefix="/books", tags=["books"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def _resolve_repo_pdf(relative_or_abs: str) -> Path:
    """Only allow PDFs under REPO_ROOT (security)."""
    p = Path(relative_or_abs).expanduser()
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    root = REPO_ROOT.resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="PDF path must be inside the backend repository directory.",
        ) from exc
    if not p.is_file():
        raise HTTPException(status_code=400, detail="File not found.")
    if p.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Must be a .pdf file.")
    return p


@router.post("/ingest-repo-pdf", response_model=dict)
async def ingest_repo_pdf(
    title: str = Form(default="FECU 101"),
    relative_path: str = Form(default="fecu1dd/fecu101.pdf"),
    db: Session = Depends(get_db),
):
    """
    Extract a PDF that already lives inside this repo (e.g. fecu1dd/fecu101.pdf).
    No OpenAI calls. Upserts ``Book`` by PDF stem when re-run.
    """
    path = _resolve_repo_pdf(relative_path)
    book = ingest_book(db, str(path), title)
    return {
        "book_id": book.id,
        "title": book.title,
        "source_id": book.source_id,
        "chunks_created": 0,
        "status": "extracted",
        "jsonl_path": book.jsonl_path,
        "message": f"Ingested from repo: {path.relative_to(REPO_ROOT)}",
    }


@router.post("/upload", response_model=dict)
async def upload_book(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Extract PDF + figures + JSONL only. Does not call OpenAI (no key required)."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files allowed")

    dest = UPLOAD_DIR / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    book = ingest_book(db, str(dest), title)
    return {
        "book_id": book.id,
        "title": book.title,
        "chunks_created": 0,
        "status": "extracted",
        "message": "PDF extracted and saved. Call POST /books/{book_id}/index to chunk + embed with OpenAI.",
    }


@router.get("/list", response_model=List[dict[str, Any]])
def list_books(db: Session = Depends(get_db)):
    """All books in the database (for UIs): id, title, index status, chunk counts for embedding/RAG."""
    rows = db.query(Book).order_by(Book.id.asc()).all()
    count_rows = db.query(Chunk.book_id, func.count(Chunk.id)).group_by(Chunk.book_id).all()
    chunk_count_by_book = {int(bid): int(n) for bid, n in count_rows}
    out: List[dict[str, Any]] = []
    for b in rows:
        nchunks = chunk_count_by_book.get(int(b.id), 0)
        ix = b.index_status or "idle"
        pdf_name = Path(b.source_pdf_path).name if b.source_pdf_path else ""
        out.append(
            {
                "id": b.id,
                "title": b.title,
                "pdf_filename": pdf_name,
                "source_id": b.source_id,
                "extraction_status": b.extraction_status,
                "index_status": ix,
                "page_count": b.page_count,
                "chunk_count": nchunks,
                "embeddings_ready": nchunks > 0 and ix == "completed",
            }
        )
    return out


@router.get("/{book_id}/index-status", response_model=dict)
def get_index_status(book_id: int, db: Session = Depends(get_db)):
    """Poll indexing progress (chunking / embeddings) for a book."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Book not found")
    return {
        "book_id": book_id,
        "index_status": book.index_status or "idle",
        "index_progress": book.index_progress or {},
        "index_error": book.index_error,
    }


@router.post("/{book_id}/index")
def index_book(
    book_id: int,
    background_tasks: BackgroundTasks,
    background: bool = True,
    max_pages: Optional[int] = Query(
        default=None,
        ge=1,
        le=2000,
        description="Process only first N pages (recommended for smoke tests). Omit for entire PDF.",
    ),
    force_restart: bool = Query(
        False,
        description="If true, clear stuck queued/running and start a new index job.",
    ),
    db: Session = Depends(get_db),
):
    """Semantic chunk + embeddings. Poll ``GET /books/{book_id}/index-status``."""
    load_all_dotenv()
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Book not found")

    key = get_openai_key()
    if not key:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No OpenAI API key configured.",
                "hint": "Set OPENAI_API_KEY or OPENAI_KEY in the environment, or put it in app/.env or .env at the repo root. Restart uvicorn after changing .env.",
            },
        )

    if book.index_status in ("running", "queued"):
        if force_restart:
            book.index_status = "idle"
            book.index_error = None
            book.index_progress = {}
            db.add(book)
            db.commit()
            db.refresh(book)
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Indexing already in progress for this book.",
                    "hint": "Use force_restart=true if a previous crash left the book stuck in queued/running.",
                    "index_status": book.index_status,
                    "poll": f"/books/{book_id}/index-status",
                },
            )

    if background:
        book.index_status = "queued"
        book.index_error = None
        book.index_progress = {
            "phase": "queued",
            "message": "Queued — will start shortly. Poll GET /books/{id}/index-status.",
        }
        db.add(book)
        db.commit()
        background_tasks.add_task(run_book_indexing, book_id, max_pages)
        return JSONResponse(
            status_code=202,
            content={
                "book_id": book_id,
                "max_pages": max_pages,
                "index_status": "queued",
                "message": "Indexing started in the background.",
                "poll_url": f"/books/{book_id}/index-status",
            },
        )

    # Synchronous (blocks until done); still updates index_progress for a single client.
    book.index_status = "running"
    book.index_error = None
    book.index_progress = {"phase": "starting", "message": "Running synchronously…"}
    db.add(book)
    db.commit()
    try:
        num_chunks = process_book_chunks(db, book, report_progress=True, max_pages=max_pages)
    except OpenAIError as exc:
        book.index_status = "failed"
        book.index_error = str(exc)
        book.index_progress = {
            **(book.index_progress or {}),
            "phase": "failed",
            "message": str(exc),
        }
        db.add(book)
        db.commit()
        raise http_exception_from_openai(exc) from exc

    db.refresh(book)
    book.index_status = "completed"
    book.index_error = None
    book.index_progress = {
        **(book.index_progress or {}),
        "phase": "completed",
        "chunks_created": num_chunks,
        "message": f"Done. {num_chunks} chunk(s) stored with embeddings.",
    }
    db.add(book)
    db.commit()

    return {
        "book_id": book_id,
        "chunks_created": num_chunks,
        "index_status": "completed",
        "max_pages": max_pages,
    }
