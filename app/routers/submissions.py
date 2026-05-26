from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from openai import OpenAIError
from pydantic import BaseModel

from app.db.repositories import assignments as assignments_repo
from app.db.repositories import submissions as submissions_repo
from app.openai_http import http_exception_from_openai
from app.services import student as student_service

router = APIRouter(prefix="/submissions", tags=["submissions"])


class StartSubmission(BaseModel):
    assignment_id: int
    student_id: str


class CheckpointSubmit(BaseModel):
    student_work: str
    friction_answer: Optional[str] = None


class AIHelpRequest(BaseModel):
    student_attempt: str


@router.post("/start")
def start_assignment(payload: StartSubmission):
    assignment = assignments_repo.get_by_id(payload.assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment["status"] not in ("ready", "published"):
        raise HTTPException(400, f"Assignment is not available for attempts yet (status: {assignment['status']})")

    existing = submissions_repo.find_existing(payload.assignment_id, payload.student_id)
    if existing:
        stages = student_service.get_assignment_stages(assignment)
        return {
            "submission_id": existing["id"],
            "status": existing["status"],
            "current_stage_index": existing.get("current_stage_index", 0),
            "total_stages": len(stages),
            "message": "Resuming existing submission.",
        }

    sub = submissions_repo.create({
        "assignment_id": payload.assignment_id,
        "student_id": payload.student_id,
        "status": "in_progress",
        "current_stage_index": 0,
        "process_log": [],
    })
    sub = student_service.append_event(sub, "assignment_started", {
        "assignment_id": payload.assignment_id,
        "student_id": payload.student_id,
    })
    stages = student_service.get_assignment_stages(assignment)
    first_stage = stages[0] if stages else None
    return {
        "submission_id": sub["id"],
        "status": "in_progress",
        "current_stage_index": 0,
        "total_stages": len(stages),
        "first_stage": first_stage,
        "message": "Assignment started. Complete each stage in order.",
    }


@router.get("/{submission_id}")
def get_submission(submission_id: int):
    sub = submissions_repo.get_by_id(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    assignment = assignments_repo.get_by_id(sub["assignment_id"])
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    stages = student_service.get_assignment_stages(assignment)
    current = student_service.get_current_stage(sub, assignment)
    completed = [e for e in (sub.get("process_log") or []) if e.get("event_type") == "checkpoint_submit"]
    return {
        "submission_id": sub["id"],
        "assignment_id": assignment["id"],
        "assignment_title": assignment.get("title"),
        "student_id": sub.get("student_id"),
        "status": sub.get("status"),
        "current_stage_index": sub.get("current_stage_index", 0),
        "total_stages": len(stages),
        "current_stage": current,
        "all_stages": stages,
        "completed_checkpoints": len(completed),
        "process_log_length": len(sub.get("process_log") or []),
    }


@router.post("/{submission_id}/checkpoint")
def submit_stage_checkpoint(submission_id: int, payload: CheckpointSubmit):
    sub = submissions_repo.get_by_id(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    if sub.get("status") == "submitted":
        raise HTTPException(400, "Assignment already submitted.")
    assignment = assignments_repo.get_by_id(sub["assignment_id"])
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    result = student_service.submit_checkpoint(sub, assignment, payload.student_work, payload.friction_answer)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/{submission_id}/ai-help")
def request_ai_help(submission_id: int, payload: AIHelpRequest):
    sub = submissions_repo.get_by_id(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    if sub.get("status") == "submitted":
        raise HTTPException(400, "Assignment already submitted.")
    assignment = assignments_repo.get_by_id(sub["assignment_id"])
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    try:
        result = student_service.generate_ai_help(sub, assignment, payload.student_attempt)
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc
    if "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/{submission_id}/log")
def get_process_log(submission_id: int):
    sub = submissions_repo.get_by_id(submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    return {"submission_id": sub["id"], "status": sub.get("status"), "log": sub.get("process_log") or []}
