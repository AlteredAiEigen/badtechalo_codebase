from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from app.db.repositories import assignments as assignments_repo
from app.db.repositories import submissions as submissions_repo
from app.services.openai_client import get_openai_client


def append_event(submission: Dict[str, Any], event_type: str, content: dict) -> Dict[str, Any]:
    log = list(submission.get("process_log") or [])
    log.append({
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "event_type": event_type,
        "stage_index": submission.get("current_stage_index", 0),
        "content": content,
    })
    return submissions_repo.update(submission["id"], {"process_log": log}) or submission


def get_assignment_stages(assignment: Dict[str, Any]) -> list:
    return assignment.get("workflow_stages") or []


def get_current_stage(submission: Dict[str, Any], assignment: Dict[str, Any]) -> Optional[dict]:
    stages = get_assignment_stages(assignment)
    idx = submission.get("current_stage_index") or 0
    if idx >= len(stages):
        return None
    return stages[idx]


def validate_checkpoint_submission(stage: dict, student_work: str, friction_answer: str | None) -> tuple[bool, str]:
    if not student_work or len(student_work.strip()) < 30:
        return False, "Please write at least a few sentences of genuine work before submitting this checkpoint."
    if stage.get("is_friction_point") and (not friction_answer or len(friction_answer.strip()) < 20):
        return False, (
            f"This stage is a friction point. You must answer the justification question: "
            f"\"{stage.get('friction_prompt', 'Why did you make this choice?')}\""
        )
    return True, ""


def submit_checkpoint(
    submission: Dict[str, Any],
    assignment: Dict[str, Any],
    student_work: str,
    friction_answer: str | None = None,
) -> Dict[str, Any]:
    stages = get_assignment_stages(assignment)
    idx = submission.get("current_stage_index") or 0
    if idx >= len(stages):
        return {"error": "All stages already completed."}
    stage = stages[idx]
    ok, msg = validate_checkpoint_submission(stage, student_work, friction_answer)
    if not ok:
        return {"error": msg}

    submission = append_event(submission, "checkpoint_submit", {
        "stage_number": stage.get("stage_number", idx + 1),
        "stage_name": stage.get("stage_name", f"Stage {idx + 1}"),
        "student_work": student_work,
        "friction_answer": friction_answer,
        "word_count": len(student_work.split()),
    })

    new_idx = idx + 1
    patch: Dict[str, Any] = {"current_stage_index": new_idx}
    if new_idx >= len(stages):
        patch["status"] = "submitted"
        patch["final_submission"] = {"completed_stages": new_idx, "total_stages": len(stages)}
    submission = submissions_repo.update(submission["id"], patch) or submission

    next_stage = stages[new_idx] if new_idx < len(stages) else None
    return {
        "status": "ok",
        "completed_stage": stage.get("stage_name"),
        "new_stage_index": submission.get("current_stage_index"),
        "next_stage": next_stage.get("stage_name") if next_stage else None,
        "all_done": submission.get("current_stage_index", 0) >= len(stages),
        "submission_status": submission.get("status"),
    }


def generate_ai_help(
    submission: Dict[str, Any],
    assignment: Dict[str, Any],
    student_attempt: str,
) -> Dict[str, Any]:
    stage = get_current_stage(submission, assignment)
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
        "ai_response_preview": (ai_response or "")[:200],
    })

    return {
        "ai_role": ai_role,
        "response": ai_response,
        "reminder": f"Remember: AI is acting as '{ai_role}' only. The work must be yours.",
    }
