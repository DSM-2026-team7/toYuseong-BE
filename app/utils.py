from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

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
) -> Optional[int]:
    return x_user_id


def require_user_id(
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> int:
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
