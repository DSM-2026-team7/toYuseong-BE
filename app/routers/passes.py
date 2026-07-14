import json
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.payment_records import completed_result_or_conflict
from app.toss import confirm_toss_payment
from app.utils import compute_d_day, get_optional_user_id, require_user_id, sync_user_pass_status, utc_now

router = APIRouter(tags=["passes"])

PASS_NOT_FOUND_ERROR = {"error": "pass_not_found", "message": "패스를 찾을 수 없어요"}
NOTICE = "할인 차액은 유성구청이 보전해요"


def _owned_pass_ids(db: Session, user_id: Optional[int]) -> set[int]:
    if user_id is None:
        return set()
    user_passes = (
        db.query(models.UserPass)
        .filter(models.UserPass.user_id == user_id, models.UserPass.status == "active")
        .all()
    )
    for user_pass in user_passes:
        sync_user_pass_status(db, user_pass)
    return {user_pass.pass_id for user_pass in user_passes if user_pass.status == "active"}


@router.get("/passes", response_model=schemas.PassListResponse)
def list_passes(
    region: Optional[str] = Query(default=None),
    x_user_id: Optional[int] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    passes = db.query(models.Pass).order_by(models.Pass.id.asc()).all()
    owned_ids = _owned_pass_ids(db, x_user_id)

    items = [
        schemas.PassListItem(
            id=p.id,
            name=p.name,
            scope=p.scope,
            period_type=p.period_type,
            duration_days=p.duration_days,
            price=p.price,
            discount_rate=p.discount_rate,
            target_desc=p.target_desc,
            owned=p.id in owned_ids,
        )
        for p in passes
    ]
    return schemas.PassListResponse(passes=items)


@router.get("/passes/{pass_id}", response_model=schemas.PassDetailResponse)
def get_pass(pass_id: int, x_user_id: Optional[int] = Depends(get_optional_user_id), db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None:
        raise HTTPException(status_code=404, detail=PASS_NOT_FOUND_ERROR)

    owned = pass_id in _owned_pass_ids(db, x_user_id)

    return schemas.PassDetailResponse(
        id=pass_row.id,
        name=pass_row.name,
        scope=pass_row.scope,
        discount_rate=pass_row.discount_rate,
        target_desc=pass_row.target_desc,
        price_options=[schemas.PassPriceOption(duration_days=pass_row.duration_days, price=pass_row.price)],
        usage_note=pass_row.usage_note,
        notice=NOTICE,
        owned=owned,
    )


@router.get("/me/passes", response_model=schemas.MyPassListResponse)
def list_my_passes(
    status: str = Query(default="active"),
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    user_passes = db.query(models.UserPass).filter(models.UserPass.user_id == x_user_id).all()

    items: list[schemas.MyPassItem] = []
    for user_pass in user_passes:
        sync_user_pass_status(db, user_pass)
        if status != "all" and user_pass.status != status:
            continue
        pass_row = db.get(models.Pass, user_pass.pass_id)
        items.append(
            schemas.MyPassItem(
                user_pass_id=user_pass.id,
                name=pass_row.name,
                scope=pass_row.scope,
                discount_rate=pass_row.discount_rate,
                status=user_pass.status,
                expires_at=user_pass.expires_at,
                d_day=compute_d_day(user_pass.expires_at),
            )
        )

    items.sort(key=lambda item: item.expires_at, reverse=True)
    return schemas.MyPassListResponse(passes=items)


@router.post("/passes/{pass_id}/purchase", response_model=schemas.PassPurchaseResponse, status_code=201)
def purchase_pass(
    pass_id: int,
    payload: schemas.PassPurchaseRequest,
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None:
        raise HTTPException(status_code=404, detail=PASS_NOT_FOUND_ERROR)

    if payload.amount != pass_row.price:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "payment_amount_mismatch",
                "message": "결제 금액이 패스 가격과 일치하지 않아요",
            },
        )
    if payload.duration_days != pass_row.duration_days:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_pass_option", "message": "선택한 패스 기간을 확인해 주세요"},
        )

    cached_result = completed_result_or_conflict(
        db,
        payment_key=payload.paymentKey,
        order_id=payload.orderId,
        user_id=x_user_id,
        purpose="pass_purchase",
        amount=payload.amount,
    )
    if cached_result is not None:
        return cached_result

    try:
        confirmed = confirm_toss_payment(payload.paymentKey, payload.orderId, payload.amount)
    except Exception:
        db.rollback()
        raise

    try:
        now = utc_now()
        expires_at = now + timedelta(days=payload.duration_days)

        user_pass = models.UserPass(
            user_id=x_user_id,
            pass_id=pass_row.id,
            status="active",
            purchased_at=now,
            expires_at=expires_at,
        )
        db.add(user_pass)
        db.flush()

        db.add(
            models.Transaction(
                user_id=x_user_id,
                type="pass_purchase",
                store_name=None,
                amount=pass_row.price,
                memo=pass_row.name,
                created_at=now,
            )
        )
        result = {
            "user_pass_id": user_pass.id,
            "name": pass_row.name,
            "status": "active",
            "expires_at": expires_at,
            "paid": pass_row.price,
            "payment_key": payload.paymentKey,
            "order_id": payload.orderId,
            "payment_status": confirmed["status"],
            "message": "패스 구매가 완료됐어요",
        }
        db.add(
            models.TossPayment(
                payment_key=payload.paymentKey,
                order_id=payload.orderId,
                user_id=x_user_id,
                purpose="pass_purchase",
                amount=payload.amount,
                status=confirmed["status"],
                method=confirmed.get("method"),
                pass_id=pass_row.id,
                user_pass_id=user_pass.id,
                result_json=json.dumps(jsonable_encoder(result), ensure_ascii=False),
                approved_at=now,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        cached_result = completed_result_or_conflict(
            db,
            payment_key=payload.paymentKey,
            order_id=payload.orderId,
            user_id=x_user_id,
            purpose="pass_purchase",
            amount=payload.amount,
        )
        if cached_result is not None:
            return cached_result
        raise HTTPException(
            status_code=409,
            detail={"error": "payment_already_processed", "message": "이미 처리된 결제예요"},
        ) from exc
    except Exception:
        db.rollback()
        raise

    return result
