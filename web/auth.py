"""관리자 인증 유틸리티: 비밀번호 해싱, JWT 토큰, require_admin 의존성."""

import hashlib
import jwt
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = "toyuseong-admin-secret-key-2026-yuseong-gu"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer()

# 로그아웃된 토큰 블랙리스트 (in-memory)
_blacklisted_tokens: set[str] = set()


def blacklist_token(token: str) -> None:
    _blacklisted_tokens.add(token)


def is_blacklisted(token: str) -> bool:
    return token in _blacklisted_tokens


# ── 비밀번호 ──


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed


# ── JWT 토큰 ──


def create_token(admin_id: int, username: str, *, must_change_password: bool = False) -> str:
    payload = {
        "sub": str(admin_id),
        "username": username,
        "must_change_password": must_change_password,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ── FastAPI 의존성 ──


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Authorization: Bearer <token> 헤더를 검증하고 payload를 반환한다."""
    token = credentials.credentials

    if is_blacklisted(token):
        raise HTTPException(status_code=401, detail="로그아웃된 토큰이에요")

    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료됐어요")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰이에요")

    if payload.get("must_change_password"):
        raise HTTPException(
            status_code=403,
            detail={"error": "password_change_required", "message": "비밀번호를 변경해야 해요"},
        )
    return payload
