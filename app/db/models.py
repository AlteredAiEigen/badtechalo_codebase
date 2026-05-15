from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, DateTime, Float, Boolean
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    source_pdf_path = Column(String, nullable=False)
    source_id = Column(String, unique=True, index=True)  # e.g., pdf stem
    extraction_status = Column(String, default="pending")  # pending, completed, failed
    jsonl_path = Column(String)
    figures_dir = Column(String)
    page_count = Column(Integer)
    # Not named "metadata" — reserved by SQLAlchemy DeclarativeBase
    record_metadata = Column(JSON, default=dict)
    # Indexing (chunk + embed) progress for UI polling
    index_status = Column(String(32), default="idle")  # idle, queued, running, completed, failed
    index_progress = Column(JSON, default=dict)
    index_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    chunks = relationship("Chunk", back_populates="book", cascade="all, delete-orphan")
    figures = relationship("FigureAsset", back_populates="book", cascade="all, delete-orphan")
    assignments = relationship("Assignment", back_populates="book")

class FigureAsset(Base):
    __tablename__ = "figure_assets"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    filename = Column(String, nullable=False)
    page = Column(Integer)
    bbox = Column(JSON)  # [x0, y0, x1, y1]
    path = Column(String, nullable=False)  # full path to PNG
    xref = Column(Integer)
    placement_index = Column(Integer)

    book = relationship("Book", back_populates="figures")

class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    topic = Column(String)
    text = Column(Text, nullable=False)
    page_start = Column(Integer)
    page_end = Column(Integer)
    figure_refs = Column(JSON, default=[])  # list of FigureAsset ids or filenames
    embedding = Column(JSON)  # store vector as list[float] for simplicity; later move to vector DB
    record_metadata = Column(JSON, default=dict)

    book = relationship("Book", back_populates="chunks")

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    title = Column(String, nullable=False)
    learning_objectives = Column(JSON, default=[])  # list of str
    workflow_stages = Column(JSON, default=[])  # list of dicts: {stage, ai_policy: "Red"|"Yellow"|"Green", guardrails, transparency_requirements}
    status = Column(String, default="draft")  # draft, approved, published
    approved_plan = Column(JSON)  # the structured plan from LLM
    prompt_template = Column(Text)  # the downstream prompt for generation
    # Chunk IDs used for plan-time RAG; final generation reuses these unless scope_query is sent again.
    plan_rag_chunk_ids = Column(JSON, nullable=True)
    created_by = Column(String)  # teacher id or name for now
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    book = relationship("Book", back_populates="assignments")
    submissions = relationship("Submission", back_populates="assignment")

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    student_id = Column(String, nullable=False)
    status = Column(String, default="in_progress")  # in_progress, submitted, graded
    current_stage_index = Column(Integer, default=0)
    process_log = Column(JSON, default=[])  # append-only list of events: {timestamp, event_type, content, metadata}
    final_submission = Column(JSON)  # the completed work
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    assignment = relationship("Assignment", back_populates="submissions")

class AIInteractionLog(Base):
    __tablename__ = "ai_interaction_logs"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"))
    stage = Column(String)
    prompt = Column(Text)
    response = Column(Text)
    tokens_used = Column(Integer)
    model = Column(String)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
