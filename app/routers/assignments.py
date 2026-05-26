from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from openai import OpenAIError
from pydantic import BaseModel

from app.db.repositories import assignments as assignments_repo
from app.db.repositories import books as books_repo
from app.openai_http import http_exception_from_openai
from app.services.assignment_design import generate_assignment_plan, generate_final_assignment

router = APIRouter(prefix="/assignments", tags=["assignments"])


def _serialize(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "book_id": a.get("book_id"),
        "title": a.get("title"),
        "status": a.get("status"),
        "visibility": a.get("visibility") or "private",
        "learning_objectives": a.get("learning_objectives") or [],
        "approved_plan": a.get("approved_plan"),
        "prompt_template": a.get("prompt_template"),
        "workflow_stages": a.get("workflow_stages") or [],
        "plan_rag_chunk_ids": a.get("plan_rag_chunk_ids"),
        "chapter_topic_ids": a.get("chapter_topic_ids"),
        "chapter_whole": a.get("chapter_whole"),
        "content_source": a.get("content_source"),
        "created_by": a.get("created_by"),
        "ui_metadata": a.get("ui_metadata") or {},
        "plan_history": a.get("plan_history") or [],
        "last_feedback": a.get("last_feedback"),
        "created_at": a.get("created_at"),
        "updated_at": a.get("updated_at"),
    }


class AssignmentCreate(BaseModel):
    book_id: int
    title: str
    learning_objectives: List[str]
    scope_query: str = ""
    notes: Optional[str] = ""
    created_by: Optional[str] = None
    ui_metadata: Optional[Dict[str, Any]] = None
    use_chapter_content: bool = True
    whole_chapter: bool = False
    chapter_topic_ids: Optional[List[str]] = None


class AssignmentMetadataUpdate(BaseModel):
    ui_metadata: Dict[str, Any]


class ApprovalPayload(BaseModel):
    approved: bool = True
    edited_plan: Optional[Dict[str, Any]] = None
    teacher_notes: Optional[str] = ""


class GeneratePayload(BaseModel):
    scope_query: Optional[str] = None
    notes: Optional[str] = ""


class RegeneratePayload(BaseModel):
    feedback: str
    chapter_topic_ids: Optional[List[str]] = None
    whole_chapter: Optional[bool] = None
    learning_objectives: Optional[List[str]] = None


class PublishPayload(BaseModel):
    visibility: Literal["public", "private"] = "private"


@router.post("/generate-plan")
def generate_plan(payload: AssignmentCreate):
    try:
        books_repo.assert_canonical_book_id(payload.book_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not books_repo.get_by_id(payload.book_id):
        raise HTTPException(404, "Book not found")
    try:
        if payload.use_chapter_content:
            if not payload.whole_chapter and not (payload.chapter_topic_ids or []):
                raise HTTPException(400, "Select whole_chapter=true or provide chapter_topic_ids.")
        elif not (payload.scope_query or "").strip():
            raise HTTPException(400, "scope_query is required when use_chapter_content=false.")
        result = generate_assignment_plan(
            payload.book_id,
            payload.title,
            payload.learning_objectives,
            payload.scope_query or "",
            payload.notes or "",
            use_chapter_content=payload.use_chapter_content,
            whole_chapter=payload.whole_chapter,
            chapter_topic_ids=payload.chapter_topic_ids,
        )
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc

    assignment = assignments_repo.create({
        "book_id": payload.book_id,
        "title": payload.title,
        "learning_objectives": payload.learning_objectives,
        "status": "draft",
        "approved_plan": result.get("plan"),
        "prompt_template": result.get("prompt_template"),
        "plan_rag_chunk_ids": result.get("rag_chunk_ids") or None,
        "chapter_topic_ids": result.get("chapter_topic_ids"),
        "chapter_whole": bool(result.get("chapter_whole")),
        "content_source": result.get("content_source") or "chapter_json",
        "created_by": payload.created_by,
        "ui_metadata": payload.ui_metadata or {},
        "workflow_stages": [],
    })

    return {
        "assignment_id": assignment["id"],
        "status": "draft",
        "plan": result.get("plan"),
        "prompt_template": result.get("prompt_template"),
        "rag_chunk_ids": result.get("rag_chunk_ids") or [],
        "content_source": result.get("content_source"),
        "chapter_topic_ids": result.get("chapter_topic_ids"),
        "scope_label": result.get("scope_label"),
        "next_step": f"Review the plan, then POST /assignments/{assignment['id']}/approve",
    }


@router.post("/{assignment_id}/approve")
def approve_plan(assignment_id: int, payload: ApprovalPayload):
    assignment = assignments_repo.get_by_id(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment["status"] not in ("draft", "approved"):
        raise HTTPException(400, f"Cannot approve assignment in status '{assignment['status']}'")
    patch: Dict[str, Any] = {}
    if payload.edited_plan:
        patch["approved_plan"] = payload.edited_plan
    patch["status"] = "approved" if payload.approved else "draft"
    assignment = assignments_repo.update(assignment_id, patch)
    return {
        "assignment_id": assignment["id"],
        "status": assignment["status"],
        "plan": assignment.get("approved_plan"),
        "next_step": (
            f"POST /assignments/{assignment['id']}/generate to create the actual assignment"
            if assignment["status"] == "approved"
            else "Edit and re-approve when ready."
        ),
    }


@router.post("/{assignment_id}/regenerate-plan")
def regenerate_plan(assignment_id: int, payload: RegeneratePayload):
    feedback = (payload.feedback or "").strip()
    if not feedback:
        raise HTTPException(400, "Feedback is required to regenerate.")
    if len(feedback) < 10:
        raise HTTPException(400, "Feedback must be at least 10 characters.")

    assignment = assignments_repo.get_by_id(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment["status"] not in ("draft", "approved", "ready"):
        raise HTTPException(
            400,
            f"Cannot regenerate a {assignment['status']} assignment. Unpublish or delete first.",
        )

    prev_plan = assignment.get("approved_plan") or {}
    prev_title = prev_plan.get("assignment_title") or prev_plan.get("title") or assignment.get("title")
    prev_theme = prev_plan.get("theme_used")
    notes_parts = [f"Teacher feedback on previous draft: {feedback}"]
    if prev_title:
        notes_parts.append(f"Avoid repeating the previous draft titled '{prev_title}'.")
    if prev_theme:
        notes_parts.append(f"Use a different theme from the previous draft (which used theme '{prev_theme}').")
    new_notes = "\n".join(notes_parts)

    topic_ids = (
        payload.chapter_topic_ids
        if payload.chapter_topic_ids is not None
        else assignment.get("chapter_topic_ids")
    )
    whole_chapter = (
        payload.whole_chapter
        if payload.whole_chapter is not None
        else bool(assignment.get("chapter_whole"))
    )
    objectives = payload.learning_objectives or assignment.get("learning_objectives") or []

    try:
        result = generate_assignment_plan(
            assignment["book_id"],
            assignment.get("title") or "",
            objectives,
            "",
            new_notes,
            use_chapter_content=True,
            whole_chapter=whole_chapter,
            chapter_topic_ids=topic_ids,
        )
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc

    history = list(assignment.get("plan_history") or [])
    history.append({
        "plan": prev_plan,
        "feedback": None,
        "generated_at": assignment.get("updated_at"),
    })

    new_plan = result.get("plan") or {}
    new_title = new_plan.get("assignment_title") or new_plan.get("title") or assignment.get("title")

    patch: Dict[str, Any] = {
        "title": new_title,
        "approved_plan": new_plan,
        "prompt_template": result.get("prompt_template"),
        "plan_rag_chunk_ids": result.get("rag_chunk_ids") or None,
        "chapter_topic_ids": result.get("chapter_topic_ids"),
        "chapter_whole": bool(result.get("chapter_whole")),
        "content_source": result.get("content_source") or "chapter_json",
        "status": "approved",
        "workflow_stages": [],
        "plan_history": history,
        "last_feedback": feedback,
        "learning_objectives": objectives,
    }
    assignment = assignments_repo.update(assignment_id, patch)
    return {
        "assignment_id": assignment["id"],
        "status": assignment["status"],
        "plan": assignment.get("approved_plan"),
        "history_count": len(history),
        "next_step": f"POST /assignments/{assignment['id']}/generate to build the new workflow",
    }


@router.post("/{assignment_id}/generate")
def generate_assignment(assignment_id: int, payload: GeneratePayload):
    assignment = assignments_repo.get_by_id(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment["status"] != "approved":
        raise HTTPException(400, f"Assignment must be approved first (current: '{assignment['status']}').")
    if not assignment.get("approved_plan"):
        raise HTTPException(400, "No approved plan found.")
    try:
        result = generate_final_assignment(
            assignment["book_id"],
            assignment["approved_plan"],
            scope_query=(payload.scope_query or "").strip(),
            notes=payload.notes or "",
            plan_rag_chunk_ids=assignment.get("plan_rag_chunk_ids"),
            content_source=assignment.get("content_source") or "chapter_json",
            chapter_topic_ids=assignment.get("chapter_topic_ids"),
            whole_chapter=bool(assignment.get("chapter_whole", True)),
        )
    except OpenAIError as exc:
        raise http_exception_from_openai(exc) from exc

    assignment = assignments_repo.update(assignment_id, {
        "status": "ready",
        "workflow_stages": result.get("stages") or result.get("instructions") or [],
    })
    return {
        "assignment_id": assignment["id"],
        "status": "ready",
        "assignment": result,
        "next_step": f"Try the assignment, then POST /assignments/{assignment['id']}/publish",
    }


@router.get("")
def list_assignments(
    status: Optional[str] = None,
    created_by: Optional[str] = None,
    class_group: Optional[str] = None,
    visible_to_teacher: Optional[str] = None,
):
    rows = assignments_repo.list_all(
        status=status,
        created_by=created_by,
        class_group=class_group,
        visible_to_teacher=visible_to_teacher,
    )
    return {"assignments": [_serialize(a) for a in rows]}


@router.patch("/{assignment_id}/metadata")
def update_metadata(assignment_id: int, payload: AssignmentMetadataUpdate):
    assignment = assignments_repo.get_by_id(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    merged = {**(assignment.get("ui_metadata") or {}), **payload.ui_metadata}
    assignment = assignments_repo.update(assignment_id, {"ui_metadata": merged})
    return _serialize(assignment)


@router.post("/{assignment_id}/publish")
def publish_assignment(assignment_id: int, payload: PublishPayload = PublishPayload()):
    assignment = assignments_repo.get_by_id(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment["status"] not in ("ready", "published"):
        raise HTTPException(400, f"Assignment must be ready before publishing (current: '{assignment['status']}').")
    if not assignment.get("workflow_stages"):
        raise HTTPException(400, "No workflow stages found.")
    meta = dict(assignment.get("ui_metadata") or {})
    meta["published_at"] = meta.get("published_at") or datetime.now(timezone.utc).isoformat()
    meta["visibility"] = payload.visibility
    assignment = assignments_repo.update(
        assignment_id,
        {"status": "published", "visibility": payload.visibility, "ui_metadata": meta},
    )
    return {
        "assignment_id": assignment["id"],
        "status": "published",
        "visibility": payload.visibility,
        "assignment": _serialize(assignment),
    }


@router.delete("/{assignment_id}")
def delete_assignment(assignment_id: int):
    if not assignments_repo.delete(assignment_id):
        raise HTTPException(404, "Assignment not found")
    return {"deleted": assignment_id}


@router.get("/{assignment_id}")
def get_assignment(assignment_id: int):
    assignment = assignments_repo.get_by_id(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return _serialize(assignment)
