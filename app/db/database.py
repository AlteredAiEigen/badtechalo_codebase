from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from app.db.models import Base
import os

# Use SQLite for simplicity in v1
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./assignment_platform.db")

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
    if not alters:
        return
    with engine.begin() as conn:
        for sql in alters:
            conn.execute(text(sql))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
