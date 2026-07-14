import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models


def completed_result_or_conflict(
    db: Session,
    *,
    payment_key: str,
    order_id: str,
    user_id: int,
    purpose: str,
    amount: int,
) -> dict[str, Any] | None:
    """같은 성공 요청은 저장 응답을 반환하고, 식별자 재사용은 차단한다."""

    existing = (
        db.query(models.TossPayment)
        .filter(
            or_(
                models.TossPayment.payment_key == payment_key,
                models.TossPayment.order_id == order_id,
            )
        )
        .first()
    )
    if existing is None:
        return None

    is_same_request = (
        existing.payment_key == payment_key
        and existing.order_id == order_id
        and existing.user_id == user_id
        and existing.purpose == purpose
        and existing.amount == amount
        and existing.status == "DONE"
    )
    if is_same_request:
        try:
            result = json.loads(existing.result_json)
        except (TypeError, ValueError):
            result = None
        if isinstance(result, dict):
            return result

    raise HTTPException(
        status_code=409,
        detail={
            "error": "payment_already_processed",
            "message": "이미 사용된 결제키 또는 주문번호예요",
        },
    )
