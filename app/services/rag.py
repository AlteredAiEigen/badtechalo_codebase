import json
from typing import Any, List, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import Book, Chunk, FigureAsset
from app.services.jsonl_util import load_page_records
from app.services.openai_client import get_openai_client

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_CHUNK_CHARS = 3000


def split_text_into_chunks(text: str, page_num: int, max_chars: int = MAX_CHUNK_CHARS) -> List[Dict[str, str]]:
    """Split page text into chunks by paragraph boundaries. No LLM call."""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return [{"topic": f"Page {page_num}", "content": text.strip()}]

    chunks: List[Dict[str, str]] = []
    current = ""
    part = 1

    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append({
                "topic": f"Page {page_num} — Part {part}",
                "content": current.strip(),
            })
            part += 1
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para

    if current.strip():
        if len(chunks) == 0:
            chunks.append({"topic": f"Page {page_num}", "content": current.strip()})
        else:
            chunks.append({"topic": f"Page {page_num} — Part {part}", "content": current.strip()})

    return chunks


def embed_texts_batch(texts: List[str]) -> List[List[float]]:
    """Embed all texts in a single API call."""
    if not texts:
        return []
    client = get_openai_client()
    truncated = [t[:8000] for t in texts]
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=truncated)
    return [d.embedding for d in resp.data]


def process_book_chunks(
    db: Session,
    book: Book,
    *,
    report_progress: bool = True,
    max_pages: Optional[int] = None,
) -> int:
    """Chunk pages (simple text split), embed in batch, store."""
    if not book.jsonl_path:
        return 0

    db.query(Chunk).filter(Chunk.book_id == book.id).delete(synchronize_session=False)
    db.commit()

    page_records = load_page_records(book.jsonl_path)
    source_pages = len(page_records)
    if max_pages is not None and max_pages > 0:
        page_records = page_records[:max_pages]
    total_pages = len(page_records)

    figure_map = {
        f.filename: f.id
        for f in db.query(FigureAsset).filter(FigureAsset.book_id == book.id).all()
    }

    def bump(**kwargs: Any) -> None:
        if not report_progress:
            return
        merged = dict(book.index_progress or {})
        merged.update(kwargs)
        book.index_progress = merged
        book.index_status = "running"
        db.add(book)
        db.commit()

    bump(
        phase="starting",
        source_pages_total=source_pages,
        pages_in_this_run=total_pages,
        total_pages=total_pages,
        page_index=0,
        chunks_total=0,
        message=f"Processing {total_pages} page(s) of {source_pages} total.",
    )

    # Step 1: split all pages into chunks (pure text, no API calls)
    all_chunks: List[Dict[str, Any]] = []
    for idx, page in enumerate(page_records):
        pnum = page.get("page", idx + 1)
        text = page.get("text", "")
        figures_on_page = page.get("figures", [])
        figure_ids = [
            fid for fid in (
                figure_map.get(f["filename"]) for f in figures_on_page if f.get("filename")
            ) if fid is not None
        ]

        sub_chunks = split_text_into_chunks(text, pnum)
        for sub in sub_chunks:
            all_chunks.append({
                "topic": sub["topic"],
                "content": sub["content"],
                "page": page.get("page"),
                "figure_ids": figure_ids,
            })

        bump(
            phase="chunking",
            total_pages=total_pages,
            page_index=idx + 1,
            chunks_total=len(all_chunks),
            message=f"Split page {idx + 1}/{total_pages} — {len(all_chunks)} chunk(s) so far.",
        )

    if not all_chunks:
        return 0

    # Step 2: embed all chunks in one batch call
    bump(
        phase="embedding",
        total_pages=total_pages,
        page_index=total_pages,
        chunks_total=len(all_chunks),
        message=f"Embedding {len(all_chunks)} chunk(s) in one batch call…",
    )

    texts = [c["content"] for c in all_chunks]
    # OpenAI batch limit is ~2048 inputs; split if needed
    BATCH_SIZE = 2000
    all_embeddings: List[List[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        all_embeddings.extend(embed_texts_batch(batch))

    # Step 3: store everything
    for ci, (chunk_data, embedding) in enumerate(zip(all_chunks, all_embeddings)):
        db.add(Chunk(
            book_id=book.id,
            chunk_index=ci,
            topic=chunk_data["topic"],
            text=chunk_data["content"],
            page_start=chunk_data["page"],
            page_end=chunk_data["page"],
            figure_refs=chunk_data["figure_ids"],
            embedding=embedding,
            record_metadata={"page": chunk_data["page"]},
        ))

    db.commit()

    bump(
        phase="completed",
        total_pages=total_pages,
        page_index=total_pages,
        chunks_total=len(all_chunks),
        message=f"Done. {len(all_chunks)} chunk(s) stored.",
    )

    return len(all_chunks)
