import json
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from app.db.models import Book, FigureAsset
from extract_pdf_for_rag import extract_pdf_for_rag_run
from app.services.jsonl_util import load_page_records

DEFAULT_EXTRACTED_ROOT = Path("extracted_Data")


def sync_figure_assets(db: Session, book: Book) -> int:
    """Replace FigureAsset rows from JSONL (paths under figures_dir)."""
    if not book.jsonl_path or not book.figures_dir:
        return 0
    db.query(FigureAsset).filter(FigureAsset.book_id == book.id).delete(synchronize_session=False)
    root = Path(book.figures_dir).resolve()
    n = 0
    for page in load_page_records(book.jsonl_path):
        pnum = page.get("page")
        for fig in page.get("figures") or []:
            fn = fig.get("filename")
            if not fn:
                continue
            path = root / fn
            db.add(
                FigureAsset(
                    book_id=book.id,
                    filename=fn,
                    page=pnum,
                    bbox=fig.get("bbox_pt"),
                    path=str(path),
                    xref=fig.get("xref"),
                    placement_index=fig.get("placement_index"),
                )
            )
            n += 1
    return n


def ingest_book(
    db: Session,
    pdf_path: str,
    title: str,
    with_figures: bool = True,
) -> Book:
    """Ingest a PDF: extract, upsert Book by source_id (same filename stem re-upload replaces row)."""
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    stem = pdf_path.stem
    dest_dir = DEFAULT_EXTRACTED_ROOT / stem
    dest_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = dest_dir / f"{stem}_rag.jsonl"
    figures_dir = dest_dir / f"{stem}_figures" if with_figures else None

    extract_pdf_for_rag_run(
        pdf_path,
        jsonl_path,
        figures_dir=figures_dir,
        progress=False,
    )

    with open(jsonl_path, "r", encoding="utf-8") as f:
        first_line = json.loads(f.readline())
        meta = first_line.get("document_metadata", {})

    book = db.query(Book).filter(Book.source_id == stem).first()
    if book:
        from app.db.models import Chunk  # noqa: PLC0415

        db.query(Chunk).filter(Chunk.book_id == book.id).delete(synchronize_session=False)
        book.title = title
        book.source_pdf_path = str(pdf_path)
        book.extraction_status = "completed"
        book.jsonl_path = str(jsonl_path)
        book.figures_dir = str(figures_dir) if figures_dir else None
        book.page_count = meta.get("page_count")
        book.record_metadata = meta
        book.index_status = "idle"
        book.index_progress = {}
        book.index_error = None
    else:
        book = Book(
            title=title,
            source_pdf_path=str(pdf_path),
            source_id=stem,
            extraction_status="completed",
            jsonl_path=str(jsonl_path),
            figures_dir=str(figures_dir) if figures_dir else None,
            page_count=meta.get("page_count"),
            record_metadata=meta,
        )
        db.add(book)

    db.flush()
    sync_figure_assets(db, book)
    db.commit()
    db.refresh(book)
    return book
