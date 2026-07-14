from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import APP_JWT_SECRET
from app.database import get_db


def utc_now() -> datetime:
    """SQLite에 저장/비교하기 쉽도록 tzinfo 없는 UTC datetime을 반환한다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_z(dt: datetime) -> str:
    """naive UTC datetime을 명세의 ISO8601 'Z' 표기 문자열로 변환한다."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_d_day(valid_until: Optional[datetime]) -> Optional[int]:
    if valid_until is None:
        return None
    return (valid_until.date() - utc_now().date()).days


def get_optional_user_id(
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[int]:
    if x_user_id is not None:
        return x_user_id
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = jwt.decode(token, APP_JWT_SECRET, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None


def require_user_id(
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> int:
    if x_user_id is None and authorization:
        x_user_id = get_optional_user_id(None, authorization)

    if x_user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "로그인이 필요해요"},
        )

    from app import models  # models가 utils를 import하므로 순환 참조를 피하려고 지연 import

    if db.get(models.User, x_user_id) is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_user", "message": "유효하지 않은 사용자예요"},
        )
    return x_user_id


def create_user_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(days=30)},
        APP_JWT_SECRET,
        algorithm="HS256",
    )


def user_roles(user) -> list[str]:
    roles: list[str] = []
    if user.customer_enabled:
        roles.append("customer")
    if user.owner_enabled:
        roles.append("owner")
    return roles


def owner_verification_status(db, user_id: int) -> str:
    from app import models

    application = (
        db.query(models.StoreApplication)
        .filter(models.StoreApplication.owner_id == user_id)
        .order_by(models.StoreApplication.applied_at.desc(), models.StoreApplication.id.desc())
        .first()
    )
    if application is not None and application.status == "pending":
        return "pending"
    store = db.query(models.Store).filter(models.Store.owner_id == user_id).first()
    if store is not None and store.verification_status == "approved":
        return "approved"
    return "none"


def seoul_day_bounds(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """서울 자정 기준 하루의 UTC-naive 시작/끝을 반환한다."""
    now = now or utc_now()
    utc_aware = now.replace(tzinfo=timezone.utc)
    seoul_tz = timezone(timedelta(hours=9))
    local = utc_aware.astimezone(seoul_tz)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def seoul_month_bounds(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """서울 시간 기준 이번 달의 UTC-naive 시작/끝을 반환한다."""
    now = now or utc_now()
    utc_aware = now.replace(tzinfo=timezone.utc)
    seoul_tz = timezone(timedelta(hours=9))
    local = utc_aware.astimezone(seoul_tz)
    start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_local.month == 12:
        end_local = start_local.replace(year=start_local.year + 1, month=1)
    else:
        end_local = start_local.replace(month=start_local.month + 1)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def seoul_month_bounds_for(year: int, month: int) -> tuple[datetime, datetime]:
    """지정한 서울 달력 월의 UTC-naive 시작/끝을 반환한다."""
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    seoul_tz = timezone(timedelta(hours=9))
    start_local = datetime(year, month, 1, tzinfo=seoul_tz)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=seoul_tz)
    else:
        end_local = datetime(year, month + 1, 1, tzinfo=seoul_tz)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def require_owner_id(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> int:
    """관리자 데모 인증.

    실제 JWT 발급 서버가 없는 현재 프로젝트에서는 Bearer 토큰으로 owner의 id
    (`Bearer 1` 또는 `Bearer owner-1`)를 받는다. 기존 데모 클라이언트를 위해
    X-User-Id도 허용한다.
    """
    owner_id = x_user_id
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            owner_id = None
        else:
            raw_id = token.removeprefix("owner-")
            if raw_id.isdigit():
                owner_id = int(raw_id)
            else:
                try:
                    payload = jwt.decode(token, APP_JWT_SECRET, algorithms=["HS256"])
                    owner_id = int(payload["sub"])
                except (jwt.PyJWTError, KeyError, TypeError, ValueError):
                    owner_id = None
    if owner_id is None:
        raise HTTPException(401, detail={"error": "unauthorized", "message": "로그인이 필요합니다."})

    from app import models
    user = db.get(models.User, owner_id)
    if user is None or user.role != "owner":
        raise HTTPException(401, detail={"error": "unauthorized", "message": "로그인이 필요합니다."})
    return owner_id


def sync_user_coupon_status(db, user_coupon, coupon) -> None:
    """active 상태인 UserCoupon이 기간을 넘겼으면 expired로 전환한다 (조회 시점 지연 평가)."""
    if user_coupon.status != "active":
        return

    if coupon.type == "time_limited":
        if coupon.time_limit_hours is None:
            return
        expiry = user_coupon.claimed_at + timedelta(hours=coupon.time_limit_hours)
    else:
        expiry = coupon.valid_until

    if expiry is not None and utc_now() > expiry:
        user_coupon.status = "expired"
        user_coupon.expired_at = expiry
        db.add(user_coupon)
        db.commit()
        db.refresh(user_coupon)


def sync_user_pass_status(db, user_pass) -> None:
    if user_pass.status == "active" and utc_now() > user_pass.expires_at:
        user_pass.status = "expired"
        db.add(user_pass)
        db.commit()
        db.refresh(user_pass)
