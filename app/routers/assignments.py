from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Assignment, Book
from app.openai_http import http_exception_from_openai
from app.services.assignment_design import generate_assignment_plan, generate_final_assignment
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

router = APIRouter(prefix="/assignments", tags=["assignments"])


class AssignmentCreate(BaseModel):
    book_id: int
    title: str
    learning_objectives: List[str]
    scope_query: str
    notes: Optional[str] = ""


class ApprovalPayload(BaseModel):
    approved: bool = True
    edited_plan: Optional[Dict[str, Any]] = None
    teacher_notes: Optional[str] = ""


class GeneratePayload(BaseModel):
    scope_query: Optional[str] = ""
    notes: Optional[str] = ""


# --- Step 1: Generate plan (draft) ---

@router.post("/generate-plan")
def generate_plan(
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
):
    """Generate assignment design plan using RAG + Decision Protocol. Saves as draft."""
    book = db.query(Book).filter(Book.id == payload.book_id).first()
    if not book:
        raise HTTPException(404, "Book not found")

    try:
        result = generate_assignment_plan(
            db,
            payload.book_id,
            payload.title,
            payload.learning_objectives,
            payload.scope_query,
            payload.notes or "",
        )
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc

    assignment = Assignment(
        book_id=payload.book_id,
        title=payload.title,
        learning_objectives=payload.learning_objectives,
        status="draft",
        approved_plan=result.get("plan"),
        prompt_template=result.get("prompt_template"),
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return {
        "assignment_id": assignment.id,
        "status": "draft",
        "plan": result.get("plan"),
        "prompt_template": result.get("prompt_template"),
        "next_step": f"Review the plan, then POST /assignments/{assignment.id}/approve",
    }


# --- Step 2: Teacher approves (or edits) the plan ---

@router.post("/{assignment_id}/approve")
def approve_plan(
    assignment_id: int,
    payload: ApprovalPayload,
    db: Session = Depends(get_db),
):
    """Teacher approves or edits the generated plan."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment.status not in ("draft", "approved"):
        raise HTTPException(400, f"Cannot approve assignment in status '{assignment.status}'")

    if payload.edited_plan:
        assignment.approved_plan = payload.edited_plan

    if payload.approved:
        assignment.status = "approved"
    else:
        assignment.status = "draft"

    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return {
        "assignment_id": assignment.id,
        "status": assignment.status,
        "plan": assignment.approved_plan,
        "next_step": (
            f"POST /assignments/{assignment.id}/generate to create the actual assignment"
            if assignment.status == "approved"
            else "Edit and re-approve when ready."
        ),
    }


# --- Step 3: Generate the actual assignment from approved plan ---

@router.post("/{assignment_id}/generate")
def generate_assignment(
    assignment_id: int,
    payload: GeneratePayload,
    db: Session = Depends(get_db),
):
    """Generate the full assignment document from the approved plan."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment.status != "approved":
        raise HTTPException(
            400,
            f"Assignment must be approved first (current: '{assignment.status}'). "
            f"POST /assignments/{assignment_id}/approve",
        )
    if not assignment.approved_plan:
        raise HTTPException(400, "No approved plan found. Generate a plan first.")

    try:
        result = generate_final_assignment(
            db,
            assignment.book_id,
            assignment.approved_plan,
            scope_query=payload.scope_query or "",
            notes=payload.notes or "",
        )
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc

    assignment.status = "published"
    assignment.workflow_stages = result.get("instructions", [])
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return {
        "assignment_id": assignment.id,
        "status": "published",
        "assignment": result,
    }


# --- Helpers ---

@router.get("/{assignment_id}")
def get_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return {
        "id": assignment.id,
        "book_id": assignment.book_id,
        "title": assignment.title,
        "status": assignment.status,
        "learning_objectives": assignment.learning_objectives,
        "approved_plan": assignment.approved_plan,
        "prompt_template": assignment.prompt_template,
        "workflow_stages": assignment.workflow_stages,
    }
