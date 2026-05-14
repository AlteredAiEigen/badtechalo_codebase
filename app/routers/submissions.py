from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Submission, Assignment
from app.openai_http import http_exception_from_openai
from app.services.student import (
    append_event,
    get_assignment_stages,
    get_current_stage,
    submit_checkpoint,
    generate_ai_help,
)
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/submissions", tags=["submissions"])


class StartSubmission(BaseModel):
    assignment_id: int
    student_id: str


class CheckpointSubmit(BaseModel):
    student_work: str
    friction_answer: Optional[str] = None


class AIHelpRequest(BaseModel):
    student_attempt: str


# --- Start an assignment as a student ---

@router.post("/start")
def start_assignment(
    payload: StartSubmission,
    db: Session = Depends(get_db),
):
    """Student starts working on a published assignment."""
    assignment = db.query(Assignment).filter(Assignment.id == payload.assignment_id).first()
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment.status != "published":
        raise HTTPException(400, f"Assignment is not published yet (status: {assignment.status})")

    existing = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == payload.assignment_id,
            Submission.student_id == payload.student_id,
        )
        .first()
    )
    if existing:
        return {
            "submission_id": existing.id,
            "status": existing.status,
            "current_stage_index": existing.current_stage_index,
            "message": "Resuming existing submission.",
        }

    sub = Submission(
        assignment_id=payload.assignment_id,
        student_id=payload.student_id,
        status="in_progress",
        current_stage_index=0,
        process_log=[],
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    append_event(sub, "assignment_started", {
        "assignment_id": payload.assignment_id,
        "student_id": payload.student_id,
    }, db)

    stages = get_assignment_stages(assignment)
    first_stage = stages[0] if stages else None

    return {
        "submission_id": sub.id,
        "status": "in_progress",
        "current_stage_index": 0,
        "total_stages": len(stages),
        "first_stage": first_stage,
        "message": "Assignment started. Complete each stage in order.",
    }


# --- Get current progress ---

@router.get("/{submission_id}")
def get_submission(
    submission_id: int,
    db: Session = Depends(get_db),
):
    """Get submission details including current stage and progress."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")

    assignment = sub.assignment
    stages = get_assignment_stages(assignment)
    current = get_current_stage(sub)

    completed_checkpoints = [
        e for e in (sub.process_log or []) if e.get("event_type") == "checkpoint_submit"
    ]

    return {
        "submission_id": sub.id,
        "assignment_id": assignment.id,
        "assignment_title": assignment.title,
        "student_id": sub.student_id,
        "status": sub.status,
        "current_stage_index": sub.current_stage_index,
        "total_stages": len(stages),
        "current_stage": current,
        "all_stages": stages,
        "completed_checkpoints": len(completed_checkpoints),
        "process_log_length": len(sub.process_log or []),
    }


# --- Submit checkpoint for current stage ---

@router.post("/{submission_id}/checkpoint")
def submit_stage_checkpoint(
    submission_id: int,
    payload: CheckpointSubmit,
    db: Session = Depends(get_db),
):
    """Submit work for the current stage. Advances to next stage on success."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    if sub.status == "submitted":
        raise HTTPException(400, "Assignment already submitted.")

    result = submit_checkpoint(db, sub, payload.student_work, payload.friction_answer)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# --- Request AI help (brain-first enforced) ---

@router.post("/{submission_id}/ai-help")
def request_ai_help(
    submission_id: int,
    payload: AIHelpRequest,
    db: Session = Depends(get_db),
):
    """Request AI help for current stage. Only works on Yellow/Green stages after student has written something."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    if sub.status == "submitted":
        raise HTTPException(400, "Assignment already submitted.")

    try:
        result = generate_ai_help(sub, payload.student_attempt, db)
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc

    if "error" in result:
        raise HTTPException(400, result)
    return result


# --- View process log ---

@router.get("/{submission_id}/log")
def get_process_log(
    submission_id: int,
    db: Session = Depends(get_db),
):
    """View the full append-only process log."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    return {
        "submission_id": sub.id,
        "status": sub.status,
        "log": sub.process_log or [],
    }
