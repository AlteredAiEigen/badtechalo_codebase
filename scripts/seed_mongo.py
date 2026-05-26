#!/usr/bin/env python3
"""Seed MongoDB Atlas with chapter content and default portal users."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.auth.deps import hash_password
from app.config_env import load_all_dotenv
from app.db.mongo import col, get_database, ping_mongo
from app.db.repositories import chapters as chapters_repo
from app.db.repositories import users as users_repo

DEFAULT_USERS = [
    ("admin@badtechalo.care", "admin123", "admin", "Platform Admin"),
    ("teacher@badtechalo.care", "teacher123", "teacher", "Demo Teacher"),
    ("student@badtechalo.care", "student123", "student", "Demo Student"),
    ("parent@badtechalo.care", "parent123", "parent", "Demo Parent"),
]

DEFAULT_CLASSES = ["Class 8A", "Class 8B", "Class 9A", "Class 10A"]


def seed_users() -> None:
    for email, password, role, name in DEFAULT_USERS:
        if users_repo.get_user_by_email(email):
            print(f"  skip user {email}")
            continue
        users_repo.create_user(email, hash_password(password), role, name)
        print(f"  created user {email} ({role})")


def seed_classes() -> None:
    for c in DEFAULT_CLASSES:
        col("classes").update_one({"name": c}, {"$set": {"name": c}}, upsert=True)
    print(f"  seeded {len(DEFAULT_CLASSES)} classes")


def seed_chapter() -> None:
    data = chapters_repo.seed_chapter_from_file()
    print("  seeded chapter from chapter.json")
    from app.db.repositories import books as books_repo

    book = books_repo.seed_canonical_book_from_chapter(data)
    print(f"  seeded canonical book id={book['id']} ({book['title']})")


def seed_student_profile() -> None:
    student = users_repo.get_user_by_email("student@badtechalo.care")
    if not student:
        return
    col("students").update_one(
        {"user_id": student["id"]},
        {
            "$set": {
                "user_id": student["id"],
                "full_name": student["full_name"],
                "class_section": "8A",
                "grade": "8",
                "roll_no": 1,
            }
        },
        upsert=True,
    )
    parent = users_repo.get_user_by_email("parent@badtechalo.care")
    if parent and student:
        col("parent_links").update_one(
            {"parent_user_id": parent["id"], "student_user_id": student["id"]},
            {"$set": {"parent_user_id": parent["id"], "student_user_id": student["id"]}},
            upsert=True,
        )


def main() -> None:
    load_all_dotenv()
    if not ping_mongo():
        print("ERROR: Cannot reach MongoDB Atlas. Check MONGODB_URI in backend/.env")
        sys.exit(1)
    print(f"Connected to database: {get_database().name}")
    seed_chapter()
    seed_classes()
    seed_users()
    seed_student_profile()
    print("Seed complete.")


if __name__ == "__main__":
    main()
