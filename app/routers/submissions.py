from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Submission
from app.openai_http import http_exception_from_openai
from app.services.student import append_event, generate_scaffold_after_attempt
from pydantic import BaseModel
from typing import List, Dict, Any

router = APIRouter(prefix="/submissions", tags=["submissions"])

class EventCreate(BaseModel):
    event_type: str
    content: Dict[str, Any]

class ScaffoldRequest(BaseModel):
    stage_name: str
    student_attempt: str

@router.post("/{submission_id}/event")
def add_process_event(
    submission_id: int,
    event: EventCreate,
    db: Session = Depends(get_db),
):
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    append_event(sub, event.event_type, event.content, db)
    return {"status": "event_logged", "log_length": len(sub.process_log)}

@router.post("/{submission_id}/scaffold")
def get_scaffold(
    submission_id: int,
    req: ScaffoldRequest,
    db: Session = Depends(get_db),
):
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    assignment = sub.assignment
    try:
        response = generate_scaffold_after_attempt(
            sub, req.stage_name, req.student_attempt, assignment
        )
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc
    # Log the interaction
    append_event(sub, "ai_scaffold", {"stage": req.stage_name, "response": response}, db)
    return {"scaffold": response}
