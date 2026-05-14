from sqlalchemy.orm import Session
from app.db.models import Submission, Assignment
from app.services.openai_client import get_openai_client

def append_event(submission: Submission, event_type: str, content: dict, db: Session):
    """Append-only event to process_log."""
    log = submission.process_log or []
    log.append({"timestamp": __import__("datetime").datetime.utcnow().isoformat(), "event_type": event_type, "content": content})
    submission.process_log = log
    db.add(submission)
    db.commit()
    db.refresh(submission)

def generate_scaffold_after_attempt(
    submission: Submission,
    stage_name: str,
    student_attempt: str,
    assignment: Assignment,
) -> str:
    """Only generate AI help AFTER student has provided an attempt. Enforces brain-first."""
    if not student_attempt or len(student_attempt.strip()) < 20:
        return "Please provide a genuine attempt first before requesting AI support."

    prompt = f"""You are a helpful learning coach. The student has already attempted this stage themselves.

Stage: {stage_name}
Assignment context (from approved plan): {assignment.approved_plan}

Student's attempt:
{student_attempt}

Provide a scaffolded response: critique, hint, or reflection prompt that helps them improve WITHOUT giving the full answer. Be encouraging and specific.
"""

    client = get_openai_client()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content
