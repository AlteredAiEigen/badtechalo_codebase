from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models import Submission, Assignment
from app.services.openai_client import get_openai_client


def append_event(submission: Submission, event_type: str, content: dict, db: Session):
    """Append-only event to process_log."""
    log = list(submission.process_log or [])
    log.append({
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "event_type": event_type,
        "stage_index": submission.current_stage_index,
        "content": content,
    })
    submission.process_log = log
    db.add(submission)
    db.commit()
    db.refresh(submission)


def get_assignment_stages(assignment: Assignment) -> list[dict]:
    """Get stages from the assignment (workflow_stages holds the generated stages)."""
    return assignment.workflow_stages or []


def get_current_stage(submission: Submission) -> Optional[dict]:
    """Return the stage dict the student is currently on, or None if done."""
    stages = get_assignment_stages(submission.assignment)
    idx = submission.current_stage_index or 0
    if idx >= len(stages):
        return None
    return stages[idx]


def validate_checkpoint_submission(
    stage: dict,
    student_work: str,
    friction_answer: str | None,
) -> tuple[bool, str]:
    """Check that the student has provided enough work for the checkpoint."""
    if not student_work or len(student_work.strip()) < 30:
        return False, "Please write at least a few sentences of genuine work before submitting this checkpoint."

    if stage.get("is_friction_point") and (not friction_answer or len(friction_answer.strip()) < 20):
        return False, (
            f"This stage is a friction point. You must answer the justification question: "
            f"\"{stage.get('friction_prompt', 'Why did you make this choice?')}\""
        )
    return True, ""


def submit_checkpoint(
    db: Session,
    submission: Submission,
    student_work: str,
    friction_answer: str | None = None,
) -> Dict[str, Any]:
    """Submit work for the current stage checkpoint and advance to next stage."""
    stages = get_assignment_stages(submission.assignment)
    idx = submission.current_stage_index or 0

    if idx >= len(stages):
        return {"error": "All stages already completed."}

    stage = stages[idx]

    ok, msg = validate_checkpoint_submission(stage, student_work, friction_answer)
    if not ok:
        return {"error": msg}

    append_event(submission, "checkpoint_submit", {
        "stage_number": stage.get("stage_number", idx + 1),
        "stage_name": stage.get("stage_name", f"Stage {idx + 1}"),
        "student_work": student_work,
        "friction_answer": friction_answer,
        "word_count": len(student_work.split()),
    }, db)

    submission.current_stage_index = idx + 1

    if idx + 1 >= len(stages):
        submission.status = "submitted"
        submission.final_submission = {
            "completed_stages": idx + 1,
            "total_stages": len(stages),
        }

    db.add(submission)
    db.commit()
    db.refresh(submission)

    next_stage = stages[idx + 1] if idx + 1 < len(stages) else None
    return {
        "status": "ok",
        "completed_stage": stage.get("stage_name"),
        "new_stage_index": submission.current_stage_index,
        "next_stage": next_stage.get("stage_name") if next_stage else None,
        "all_done": submission.current_stage_index >= len(stages),
        "submission_status": submission.status,
    }


def generate_ai_help(
    submission: Submission,
    student_attempt: str,
    db: Session,
) -> Dict[str, Any]:
    """
    AI help for the current stage. Enforces:
    - Stage must be Yellow or Green (not Red)
    - Student must have written something first (brain-first)
    - AI plays the specific role defined for this stage
    """
    stage = get_current_stage(submission)
    if not stage:
        return {"error": "No current stage — assignment may be complete."}

    policy = (stage.get("ai_policy") or "Red").strip()
    if policy == "Red":
        return {
            "error": "AI is not permitted at this stage.",
            "reason": stage.get("ai_guidance", "This stage requires your own thinking."),
        }

    if not student_attempt or len(student_attempt.strip()) < 30:
        return {
            "error": "Brain-first: you must write your own work first (at least a few sentences) before requesting AI help.",
            "brain_first_requirement": stage.get("brain_first_requirement", ""),
        }

    ai_role = stage.get("ai_role") or "learning coach"
    stage_name = stage.get("stage_name", "this stage")

    prompt = f"""You are acting as a "{ai_role}" for a student working on an assignment.

IMPORTANT RULES:
- You are ONLY a {ai_role}. Do NOT do the student's work for them.
- Do NOT write their essay/answer. Give feedback, hints, questions, or suggestions.
- The student has already produced their own attempt (brain-first). Help them improve it.
- Be encouraging but honest. Point out strengths and areas to improve.

Stage: {stage_name}
Stage instructions: {stage.get('instructions', '')}
AI guidance for this stage: {stage.get('ai_guidance', '')}

Student's attempt so far:
{student_attempt}

Provide your response as a {ai_role}:"""

    client = get_openai_client()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
    )
    ai_response = resp.choices[0].message.content

    append_event(submission, "ai_interaction", {
        "stage_name": stage_name,
        "ai_role": ai_role,
        "student_attempt_preview": student_attempt[:200],
        "ai_response_preview": ai_response[:200],
    }, db)

    return {
        "ai_role": ai_role,
        "response": ai_response,
        "reminder": f"Remember: AI is acting as '{ai_role}' only. The work must be yours.",
    }
