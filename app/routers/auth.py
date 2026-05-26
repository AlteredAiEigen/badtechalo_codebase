from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.auth.deps import create_access_token, hash_password, verify_password, get_current_user as auth_me
from app.db.repositories import users as users_repo

router = APIRouter(prefix="/auth", tags=["auth"])

AppRole = Literal["student", "teacher", "parent", "admin"]


class RegisterBody(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: AppRole


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
def register(body: RegisterBody):
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    try:
        user = users_repo.create_user(
            body.email,
            hash_password(body.password),
            body.role,
            body.full_name,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    token = create_access_token(user["id"], user["role"], user["email"])
    return {"access_token": token, "token_type": "bearer", "user": users_repo.public_user(user)}


@router.post("/login")
def login(body: LoginBody):
    user = users_repo.get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    token = create_access_token(user["id"], user["role"], user["email"])
    return {"access_token": token, "token_type": "bearer", "user": users_repo.public_user(user)}


@router.get("/me")
def me(user=Depends(auth_me)):
    return users_repo.public_user(user)


@router.post("/logout")
def logout():
    return {"ok": True}
