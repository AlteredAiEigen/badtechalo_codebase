from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.deps import get_current_user, require_roles
from app.db.mongo import col
from app.db.repositories import portal as portal_repo

router = APIRouter(prefix="/portal", tags=["portal"])


@router.get("/me/student")
def my_student_profile(user=Depends(get_current_user)):
    doc = col("students").find_one({"user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Student profile not found")
    return doc


@router.get("/me/children")
def my_children(user=Depends(require_roles("parent"))):
    links = list(col("parent_links").find({"parent_user_id": user["id"]}, {"_id": 0}))
    ids = [l["student_user_id"] for l in links]
    if not ids:
        return {"children": []}
    students = list(col("students").find({"user_id": {"$in": ids}}, {"_id": 0}))
    return {"children": students}


@router.get("/school-events")
def list_school_events(user=Depends(get_current_user)):
    return {"events": portal_repo.list_docs("school_events")}


@router.get("/users")
def list_users(role: Optional[str] = None, user=Depends(require_roles("admin", "teacher"))):
    q: Dict[str, Any] = {}
    if role:
        q["role"] = role
    rows = list(col("users").find(q, {"_id": 0, "password_hash": 0}).sort("id", 1))
    return {"users": rows}


@router.get("/visitors")
def list_visitors(user=Depends(require_roles("admin"))):
    return {"visitors": portal_repo.list_docs("visitors")}


@router.get("/classes")
def list_classes():
    rows = list(col("classes").find({}, {"_id": 0}))
    if not rows:
        return {"classes": ["Class 8A", "Class 8B", "Class 9A", "Class 10A"]}
    return {"classes": [r.get("name") for r in rows if r.get("name")]}


@router.get("/students")
def list_students(class_section: Optional[str] = None, user=Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if class_section:
        q["class_section"] = class_section.replace("Class ", "").replace("class ", "")
    return {"students": portal_repo.list_docs("students", q)}


@router.get("/attendance")
def list_attendance(student_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {"student_id": student_id} if student_id else {}
    return {"attendance": portal_repo.list_docs("attendance", q)}


class AttendanceBody(BaseModel):
    student_id: str
    status: str
    marked_at: Optional[str] = None
    notes: Optional[str] = ""


@router.post("/attendance")
def create_attendance(body: AttendanceBody, user=Depends(require_roles("teacher", "admin"))):
    doc = portal_repo.insert_doc("attendance", body.model_dump())
    return doc


@router.get("/calendar")
def list_calendar(user=Depends(get_current_user)):
    return {"events": portal_repo.list_docs("class_calendar")}


class CalendarBody(BaseModel):
    title: str
    description: Optional[str] = ""
    event_date: str
    class_group: Optional[str] = ""
    subject: Optional[str] = ""


@router.post("/calendar")
def create_calendar(body: CalendarBody, user=Depends(require_roles("teacher", "admin"))):
    return portal_repo.insert_doc("class_calendar", {**body.model_dump(), "created_by": user["id"]})


@router.patch("/calendar/{event_id}")
def update_calendar(event_id: str, body: CalendarBody, user=Depends(require_roles("teacher", "admin"))):
    doc = portal_repo.update_doc("class_calendar", event_id, body.model_dump())
    if not doc:
        raise HTTPException(404, "Event not found")
    return doc


@router.delete("/calendar/{event_id}")
def delete_calendar(event_id: str, user=Depends(require_roles("teacher", "admin"))):
    if not portal_repo.delete_doc("class_calendar", event_id):
        raise HTTPException(404, "Event not found")
    return {"deleted": event_id}


@router.get("/announcements")
def list_announcements(user=Depends(get_current_user)):
    return {"announcements": portal_repo.list_docs("announcements")}


class AnnouncementBody(BaseModel):
    title: str
    content: str
    priority: str = "normal"


@router.post("/announcements")
def create_announcement(body: AnnouncementBody, user=Depends(require_roles("teacher", "admin"))):
    return portal_repo.insert_doc("announcements", {**body.model_dump(), "created_by": user["id"]})


@router.get("/notes")
def list_notes(user=Depends(get_current_user)):
    return {"notes": portal_repo.list_docs("notes")}


class NoteBody(BaseModel):
    title: str
    content: str
    class_group: Optional[str] = ""
    subject: Optional[str] = ""


@router.post("/notes")
def create_note(body: NoteBody, user=Depends(require_roles("teacher", "admin"))):
    return portal_repo.insert_doc("notes", {**body.model_dump(), "teacher_id": user["id"]})


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, user=Depends(require_roles("teacher", "admin"))):
    if not portal_repo.delete_doc("notes", note_id):
        raise HTTPException(404, "Note not found")
    return {"deleted": note_id}


@router.get("/meetings")
def list_meetings(user=Depends(get_current_user)):
    return {"meetings": portal_repo.list_docs("meetings")}


class MeetingBody(BaseModel):
    title: str
    scheduled_at: str
    student_id: Optional[str] = None
    notes: Optional[str] = ""


@router.post("/meetings")
def create_meeting(body: MeetingBody, user=Depends(require_roles("parent", "teacher", "admin"))):
    return portal_repo.insert_doc("meetings", {**body.model_dump(), "parent_id": user["id"]})


@router.get("/test-marks")
def list_test_marks(class_group: Optional[str] = None, user=Depends(get_current_user)):
    q = {"class_group": class_group} if class_group else {}
    return {"marks": portal_repo.list_docs("test_marks", q)}


class TestMarkBody(BaseModel):
    student_id: str
    student_name: str
    subject: str
    test_name: str
    score: float
    max_score: float = 100
    class_group: Optional[str] = ""


@router.post("/test-marks")
def upsert_test_mark(body: TestMarkBody, user=Depends(require_roles("teacher", "admin"))):
    return portal_repo.insert_doc("test_marks", body.model_dump())


@router.get("/fees")
def list_fees(student_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {"student_id": student_id} if student_id else {}
    return {"fees": portal_repo.list_docs("fees", q)}


@router.get("/remarks")
def list_remarks(student_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {"student_id": student_id} if student_id else {}
    return {"remarks": portal_repo.list_docs("teacher_remarks", q)}


@router.get("/badges")
def list_badges(student_id: Optional[str] = None, user=Depends(get_current_user)):
    q = {"student_id": student_id} if student_id else {}
    return {"badges": portal_repo.list_docs("parent_badges", q)}


@router.get("/syllabus-progress")
def syllabus_progress(class_group: Optional[str] = None, user=Depends(get_current_user)):
    q = {"class_group": class_group} if class_group else {}
    return {"progress": portal_repo.list_docs("syllabus_progress", q)}


class SyllabusProgressBody(BaseModel):
    class_group: str
    subject: str
    chapter: str
    topic: str
    completed: bool = True


@router.post("/syllabus-progress")
def mark_syllabus(body: SyllabusProgressBody, user=Depends(require_roles("teacher", "admin"))):
    return portal_repo.insert_doc("syllabus_progress", body.model_dump())
