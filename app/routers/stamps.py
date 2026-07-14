import base64
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import require_user_id, seoul_day_bounds, utc_now

router = APIRouter(tags=["stamps"])

INVALID_QR_ERROR = {"error": "invalid_qr", "message": "유효하지 않은 QR이에요"}
ALREADY_STAMPED_ERROR = {"error": "already_stamped_today", "message": "오늘은 이미 적립했어요"}
ALREADY_USED_QR_ERROR = {"error": "already_used", "message": "이미 처리된 QR이에요"}

def stamped_today(db: Session, user_id: int, now: Optional[datetime] = None) -> bool:
    start, end = seoul_day_bounds(now)
    return (
        db.query(models.Transaction)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.type == "stamp_earn",
            models.Transaction.created_at >= start,
            models.Transaction.created_at < end,
        )
        .first()
        is not None
    )


def _decode_customer_token(token: str) -> int:
    """customer_token은 QR 방식 미확정 상태의 임시 규약: base64(JSON {"user": <id>})."""
    padded = token + "=" * (-len(token) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            data = json.loads(decoder(padded.encode("utf-8")))
            return int(data["user"])
        except Exception:
            continue
    raise ValueError("invalid customer_token")


def _earn_stamp(
    db: Session,
    user_id: int,
    store: models.Store,
    now: datetime,
    amount: Optional[int] = None,
) -> dict:
    """스탬프 1개를 적립하고 응답 필드를 dict로 돌려준다. 커밋은 호출자 책임.

    POST /stamps(레거시)와 POST /scan(신규, type=stamp) 양쪽이 이 로직을 공유한다.
    """
    policy = (
        db.query(models.StampPolicy)
        .filter(models.StampPolicy.store_id == store.id)
        .first()
    )
    if policy is None or not policy.active:
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)
    if (amount or 0) < policy.min_amount:
        raise HTTPException(
            status_code=400,
            detail={"error": "stamp_minimum_not_met", "message": "기준 금액을 충족하지 못했습니다."},
        )
    if stamped_today(db, user_id, now):
        raise HTTPException(status_code=409, detail=ALREADY_STAMPED_ERROR)

    card = (
        db.query(models.StampCard)
        .filter(models.StampCard.user_id == user_id, models.StampCard.store_id == store.id)
        .first()
    )

    card_created = False
    if card is None:
        card = models.StampCard(
            user_id=user_id,
            store_id=store.id,
            current=0,
            completed_count=0,
            updated_at=now,
        )
        db.add(card)
        db.flush()
        card_created = True

    if policy.completion_limit is not None and card.completed_count >= policy.completion_limit:
        raise HTTPException(
            status_code=409,
            detail={"error": "stamp_completion_limit_reached", "message": "스탬프 완성 가능 횟수를 모두 사용했어요"},
        )

    card.current += 1
    card.updated_at = now

    db.add(
        models.Transaction(
            user_id=user_id,
            type="stamp_earn",
            store_name=store.name,
            store_id=store.id,
            amount=None,
            memo=f"+1 · {card.current}/{policy.goal}",
            created_at=now,
        )
    )

    reward_reached = card.current >= policy.goal
    response_current = card.current
    reward_coupon_payload: Optional[schemas.RewardCoupon] = None
    card_reset_to: Optional[int] = None

    if reward_reached:
        reward_valid_days = policy.reward_valid_days
        valid_until = now + timedelta(days=reward_valid_days) if reward_valid_days is not None else None
        reward_coupon_row = models.Coupon(
            store_id=store.id,
            type=policy.reward_type,
            title=f"{policy.reward} 쿠폰",
            value=policy.reward_value,
            target=policy.reward,
            valid_until=valid_until,
            time_limit_hours=None,
            store_only=True,
            min_payment=policy.reward_min_payment,
            max_discount=policy.reward_max_discount,
            is_coupon_infinity=True,
            status="active",
            created_at=now,
            source="stamp_reward",
        )
        db.add(reward_coupon_row)
        db.flush()

        user_coupon = models.UserCoupon(
            user_id=user_id,
            coupon_id=reward_coupon_row.id,
            status="active",
            claimed_at=now,
            used_at=None,
            expired_at=None,
        )
        db.add(user_coupon)
        db.flush()

        db.add(
            models.Transaction(
                user_id=user_id,
                type="reward_issue",
                store_name=store.name,
                store_id=store.id,
                amount=None,
                memo=f"스탬프 {policy.goal}/{policy.goal}",
                created_at=now,
            )
        )

        card.current = 0
        card.completed_count += 1
        card_reset_to = 0

        reward_coupon_payload = schemas.RewardCoupon(
            user_coupon_id=user_coupon.id,
            title=reward_coupon_row.title,
            d_day=reward_valid_days,
        )

    if reward_reached:
        message = f"{policy.goal}개 완성! 리워드 쿠폰이 발급됐어요"
    elif card_created:
        message = f"{store.name} 스탬프가 시작됐어요"
    else:
        message = "스탬프 1개 적립됐어요"

    return {
        "store_name": store.name,
        "current": response_current,
        "goal": policy.goal,
        "reward_reached": reward_reached,
        "reward": policy.reward if reward_reached else None,
        "card_created": card_created,
        "reward_coupon": reward_coupon_payload,
        "card_reset_to": card_reset_to,
        "message": message,
    }


@router.post("/stamps", response_model=schemas.StampResponse)
def create_stamp(payload: schemas.StampRequest, db: Session = Depends(get_db)):
    """레거시 플로우: 손님이 자기 QR(customer_token)을 띄우고 가게가 스캔.

    새 플로우는 가게가 QR을 띄우고 손님이 스캔하는 POST /scan이다. 기존 연동과의
    호환을 위해 이 엔드포인트는 그대로 남겨둔다.
    """
    try:
        user_id = _decode_customer_token(payload.customer_token)
    except ValueError:
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)

    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)

    store = db.get(models.Store, payload.store_id)
    if store is None:
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)

    now = utc_now()
    result = _earn_stamp(db, user_id, store, now, amount=payload.amount)
    db.commit()

    return schemas.StampResponse(**result)


@router.post("/scan")
def scan_qr(
    payload: schemas.ScanRequest,
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """새 플로우: 가게가 만들어 화면에 띄운 QR(PaymentQr)을 손님이 스캔해서 제출한다.

    QR의 type에 따라 분기한다:
    - stamp: 즉시 스탬프 적립(기존 POST /stamps와 동일 로직)
    - payment: 결제 준비 상태만 알려주고, 이후 손님 앱은 그 store_id/amount로
      GET /checkout/benefits → POST /checkout을 이어서 호출한다.
    스탬프 QR은 적립 성공 즉시 소진되고, 결제 QR은 SCANNED 상태로 예약한 뒤
    POST /checkout에서 결제가 성공해야 최종 소진(CONSUMED)된다.
    """
    qr = (
        db.query(models.PaymentQr)
        .filter(models.PaymentQr.token == payload.qr_token)
        .first()
    )
    if qr is None:
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)
    if qr.status != "WAITING":
        raise HTTPException(status_code=409, detail=ALREADY_USED_QR_ERROR)
    if qr.expires_at is not None and utc_now() > qr.expires_at:
        qr.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=410, detail={"error": "expired_qr", "message": "만료된 QR이에요"})

    store = db.get(models.Store, qr.store_id)
    if store is None:
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)

    now = utc_now()

    if qr.type == "stamp":
        # _earn_stamp가 400/409를 던질 수 있으니, 성공했을 때만 QR을 소진 처리한다
        # (스탬프 적립이 실패하면 같은 QR을 나중에 다시 스캔할 수 있어야 하므로).
        result = _earn_stamp(db, x_user_id, store, now, amount=qr.amount)
        qr.status = "CONSUMED"
        qr.consumed_at = now
        qr.consumed_by = x_user_id
        db.commit()
        return {"kind": "stamp", "amount": qr.amount, **result}

    if qr.type != "payment":
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)

    qr.status = "SCANNED"
    qr.scanned_at = now
    qr.consumed_by = x_user_id
    db.commit()

    return {
        "kind": "payment",
        "store_id": store.id,
        "store_name": store.name,
        "amount": qr.amount,
        "qr_token": qr.token,
        "checkout_ready": True,
    }
