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
    passes = (
        db.query(models.Pass)
        .filter(models.Pass.sale_status == "on_sale")
        .order_by(models.Pass.id.asc())
        .all()
    )
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
            max_discount_amount=p.max_discount_amount,
            target_desc=p.target_desc,
            owned=p.id in owned_ids,
        )
        for p in passes
    ]
    return schemas.PassListResponse(passes=items)


@router.get("/passes/{pass_id}", response_model=schemas.PassDetailResponse)
def get_pass(pass_id: int, x_user_id: Optional[int] = Depends(get_optional_user_id), db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None or pass_row.sale_status != "on_sale":
        raise HTTPException(status_code=404, detail=PASS_NOT_FOUND_ERROR)

    owned = pass_id in _owned_pass_ids(db, x_user_id)

    tiers = (
        db.query(models.PassPriceTier)
        .filter(models.PassPriceTier.pass_id == pass_id)
        .order_by(models.PassPriceTier.duration_days.asc())
        .all()
    )
    return schemas.PassDetailResponse(
        id=pass_row.id,
        name=pass_row.name,
        scope=pass_row.scope,
        discount_rate=pass_row.discount_rate,
        max_discount_amount=pass_row.max_discount_amount,
        target_desc=pass_row.target_desc,
        price_options=(
            [schemas.PassPriceOption(duration_days=t.duration_days, price=t.price) for t in tiers]
            or [schemas.PassPriceOption(duration_days=pass_row.duration_days, price=pass_row.price)]
        ),
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
        if pass_row is None:
            continue
        discount_limit = user_pass.discount_limit
        if discount_limit is None:
            discount_limit = pass_row.max_discount_amount
        remaining_discount = (
            max(discount_limit - user_pass.discount_used, 0) if discount_limit is not None else None
        )
        items.append(
            schemas.MyPassItem(
                user_pass_id=user_pass.id,
                name=user_pass.name_snapshot or pass_row.name,
                scope=user_pass.scope_snapshot or pass_row.scope,
                discount_rate=user_pass.discount_rate_snapshot or pass_row.discount_rate,
                status=user_pass.status,
                expires_at=user_pass.expires_at,
                d_day=compute_d_day(user_pass.expires_at),
                discount_used=user_pass.discount_used,
                discount_limit=discount_limit,
                remaining_discount=remaining_discount,
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
    if pass_row is None or pass_row.sale_status != "on_sale":
        raise HTTPException(status_code=404, detail=PASS_NOT_FOUND_ERROR)

    tier = (
        db.query(models.PassPriceTier)
        .filter(
            models.PassPriceTier.pass_id == pass_id,
            models.PassPriceTier.duration_days == payload.duration_days,
        )
        .first()
    )
    expected_price = tier.price if tier is not None else pass_row.price
    if payload.amount != expected_price:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "payment_amount_mismatch",
                "message": "결제 금액이 패스 가격과 일치하지 않아요",
            },
        )
    if tier is None and payload.duration_days != pass_row.duration_days:
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
        user_pass = (
            db.query(models.UserPass)
            .filter(
                models.UserPass.user_id == x_user_id,
                models.UserPass.pass_id == pass_row.id,
                models.UserPass.status == "active",
            )
            .first()
        )
        extended = user_pass is not None
        if user_pass is not None:
            if user_pass.name_snapshot is None:
                user_pass.name_snapshot = pass_row.name
                user_pass.scope_snapshot = pass_row.scope
                user_pass.scope_category_snapshot = pass_row.scope_category
                user_pass.scope_store_id_snapshot = pass_row.scope_store_id
                user_pass.discount_rate_snapshot = pass_row.discount_rate
            if user_pass.max_discount_snapshot is None:
                user_pass.max_discount_snapshot = pass_row.max_discount_amount
            base_expiry = max(user_pass.expires_at, now)
            user_pass.expires_at = base_expiry + timedelta(days=payload.duration_days)
            additional_limit = user_pass.max_discount_snapshot
            if additional_limit is not None:
                current_limit = user_pass.discount_limit or additional_limit
                user_pass.discount_limit = current_limit + additional_limit
        else:
            user_pass = models.UserPass(
                user_id=x_user_id,
                pass_id=pass_row.id,
                status="active",
                purchased_at=now,
                expires_at=now + timedelta(days=payload.duration_days),
                discount_used=0,
                discount_limit=pass_row.max_discount_amount,
                name_snapshot=pass_row.name,
                scope_snapshot=pass_row.scope,
                scope_category_snapshot=pass_row.scope_category,
                scope_store_id_snapshot=pass_row.scope_store_id,
                discount_rate_snapshot=pass_row.discount_rate,
                max_discount_snapshot=pass_row.max_discount_amount,
            )
            db.add(user_pass)
            db.flush()
        expires_at = user_pass.expires_at
        effective_name = user_pass.name_snapshot or pass_row.name

        db.add(
            models.Transaction(
                user_id=x_user_id,
                type="pass_purchase",
                store_name=None,
                store_id=None,
                amount=expected_price,
                memo=f"{effective_name} 기간 연장" if extended else effective_name,
                created_at=now,
            )
        )
        result = {
            "user_pass_id": user_pass.id,
            "name": effective_name,
            "status": "active",
            "expires_at": expires_at,
            "paid": expected_price,
            "payment_key": payload.paymentKey,
            "order_id": payload.orderId,
            "payment_status": confirmed["status"],
            "extended": extended,
            "discount_limit": user_pass.discount_limit,
            "remaining_discount": (
                max(user_pass.discount_limit - user_pass.discount_used, 0)
                if user_pass.discount_limit is not None
                else None
            ),
            "message": "패스 기간이 연장됐어요" if extended else "패스 구매가 완료됐어요",
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
