from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from web.auth import hash_password, verify_password, create_token

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    admin_id: int
    name: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """관리자 로그인: username + password → JWT 토큰 반환."""
    admin = (
        db.query(models.AdminUser)
        .filter(models.AdminUser.username == payload.username)
        .first()
    )
    if admin is None or not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_credentials", "message": "아이디 또는 비밀번호가 올바르지 않아요"},
        )

    token = create_token(admin.id, admin.username)
    return LoginResponse(token=token, admin_id=admin.id, name=admin.name)
