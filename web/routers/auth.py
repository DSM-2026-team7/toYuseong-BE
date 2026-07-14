from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from web.auth import (
    blacklist_token,
    create_token,
    decode_token,
    hash_password,
    security,
    verify_password,
)

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    admin_id: int
    name: str
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    new_password: str


class ChangePasswordResponse(BaseModel):
    token: str
    message: str


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

    token = create_token(
        admin.id,
        admin.username,
        must_change_password=admin.must_change_password,
    )
    return LoginResponse(
        token=token,
        admin_id=admin.id,
        name=admin.name,
        must_change_password=admin.must_change_password,
    )


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """비밀번호 변경: 초기 비밀번호 변경 또는 일반 비밀번호 변경 모두 지원.

    이 엔드포인트는 require_admin 의존성을 사용하지 않아
    must_change_password=true 상태에서도 호출 가능하다.
    """
    import jwt as pyjwt

    try:
        token_payload = decode_token(credentials.credentials)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료됐어요")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰이에요")

    admin_id = int(token_payload["sub"])
    admin = db.get(models.AdminUser, admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="관리자를 찾을 수 없어요")

    if len(payload.new_password) < 4:
        raise HTTPException(
            status_code=422,
            detail={"error": "weak_password", "message": "비밀번호는 4자 이상이어야 해요"},
        )

    admin.hashed_password = hash_password(payload.new_password)
    admin.must_change_password = False
    db.commit()

    # 새 토큰 발급 (must_change_password=False)
    new_token = create_token(admin.id, admin.username, must_change_password=False)
    return ChangePasswordResponse(token=new_token, message="비밀번호가 변경됐어요")


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """로그아웃: 현재 토큰을 무효화한다."""
    blacklist_token(credentials.credentials)
    return {"message": "로그아웃됐어요"}
