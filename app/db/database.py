from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
import os

# backend/app/db/database.py -> backend/
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _resolve_database_url() -> str:
    """
    Default SQLite file is always next to the backend app (not the process cwd),
    so uvicorn, Streamlit, and scripts see the same books regardless of launch directory.
    Relative paths in DATABASE_URL are resolved against _BACKEND_DIR.
    """
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        p = (_BACKEND_DIR / "assignment_platform.db").resolve()
        return f"sqlite:///{p.as_posix()}"
    if raw.startswith("sqlite:///"):
        rest = raw[len("sqlite:///") :]
        candidate = Path(rest)
        if not candidate.is_absolute():
            p = (_BACKEND_DIR / candidate).resolve()
            return f"sqlite:///{p.as_posix()}"
    return raw


DATABASE_URL = _resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def migrate_sqlite_schema() -> None:
    """Add columns introduced after first deploy (SQLite has no ALTER migration by default)."""
    if not str(engine.url).startswith("sqlite"):
        return
    insp = inspect(engine)
    if "books" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("books")}
    alters: list[str] = []
    if "index_status" not in existing:
        alters.append("ALTER TABLE books ADD COLUMN index_status VARCHAR(32) DEFAULT 'idle'")
    if "index_progress" not in existing:
        alters.append("ALTER TABLE books ADD COLUMN index_progress TEXT")
    if "index_error" not in existing:
        alters.append("ALTER TABLE books ADD COLUMN index_error TEXT")
    if alters:
        with engine.begin() as conn:
            for sql in alters:
                conn.execute(text(sql))

    tables = insp.get_table_names()
    if "assignments" not in tables:
        return
    acols = {c["name"] for c in insp.get_columns("assignments")}
    with engine.begin() as conn:
        if "plan_rag_chunk_ids" not in acols:
            conn.execute(text("ALTER TABLE assignments ADD COLUMN plan_rag_chunk_ids TEXT"))
        if "chapter_topic_ids" not in acols:
            conn.execute(text("ALTER TABLE assignments ADD COLUMN chapter_topic_ids TEXT"))
        if "content_source" not in acols:
            conn.execute(text("ALTER TABLE assignments ADD COLUMN content_source VARCHAR(32) DEFAULT 'chapter_json'"))
        if "chapter_whole" not in acols:
            conn.execute(text("ALTER TABLE assignments ADD COLUMN chapter_whole BOOLEAN DEFAULT 1"))
        if "ui_metadata" not in acols:
            conn.execute(text("ALTER TABLE assignments ADD COLUMN ui_metadata TEXT"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
