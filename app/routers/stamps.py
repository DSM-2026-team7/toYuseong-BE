import base64
import json
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import utc_now

router = APIRouter(tags=["stamps"])

INVALID_QR_ERROR = {"error": "invalid_qr", "message": "유효하지 않은 QR이에요"}
ALREADY_STAMPED_ERROR = {"error": "already_stamped_today", "message": "오늘은 이미 적립했어요"}

REWARD_COUPON_VALID_DAYS = 30


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


@router.post("/stamps", response_model=schemas.StampResponse)
def create_stamp(payload: schemas.StampRequest, db: Session = Depends(get_db)):
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

    policy = (
        db.query(models.StampPolicy)
        .filter(models.StampPolicy.store_id == store.id)
        .first()
    )
    if policy is None:
        raise HTTPException(status_code=400, detail=INVALID_QR_ERROR)

    now = utc_now()

    card = (
        db.query(models.StampCard)
        .filter(models.StampCard.user_id == user_id, models.StampCard.store_id == store.id)
        .first()
    )

    card_created = False
    if card is None:
        card = models.StampCard(user_id=user_id, store_id=store.id, current=0, updated_at=now)
        db.add(card)
        db.flush()
        card_created = True
    elif card.updated_at.date() == now.date():
        raise HTTPException(status_code=409, detail=ALREADY_STAMPED_ERROR)

    card.current += 1
    card.updated_at = now

    db.add(
        models.Transaction(
            user_id=user_id,
            type="stamp_earn",
            store_name=store.name,
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
        valid_until = now + timedelta(days=REWARD_COUPON_VALID_DAYS)
        reward_coupon_row = models.Coupon(
            store_id=store.id,
            type="discount_amount",
            title=f"{policy.reward} 쿠폰",
            value=0,
            target=policy.reward,
            valid_until=valid_until,
            time_limit_hours=None,
            store_only=True,
            min_payment=0,
            max_discount=None,
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
                amount=None,
                memo=f"스탬프 {policy.goal}/{policy.goal}",
                created_at=now,
            )
        )

        card.current = 0
        card_reset_to = 0

        reward_coupon_payload = schemas.RewardCoupon(
            user_coupon_id=user_coupon.id,
            title=reward_coupon_row.title,
            d_day=REWARD_COUPON_VALID_DAYS,
        )

    if reward_reached:
        message = "5개 완성! 리워드 쿠폰이 발급됐어요"
    elif card_created:
        message = f"{store.name} 스탬프가 시작됐어요"
    else:
        message = "스탬프 1개 적립됐어요"

    db.commit()

    return schemas.StampResponse(
        store_name=store.name,
        current=response_current,
        goal=policy.goal,
        reward_reached=reward_reached,
        reward=policy.reward if reward_reached else None,
        card_created=card_created,
        reward_coupon=reward_coupon_payload,
        card_reset_to=card_reset_to,
        message=message,
    )
