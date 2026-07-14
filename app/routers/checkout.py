import json
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.payment_records import completed_result_or_conflict
from app.toss import confirm_toss_payment
from app.utils import require_user_id, sync_user_coupon_status, sync_user_pass_status, utc_now

router = APIRouter(tags=["checkout"])

STORE_NOT_FOUND_ERROR = {"error": "store_not_found", "message": "매장을 찾을 수 없어요"}
INVALID_BENEFIT_ERROR = {"error": "invalid_benefit", "message": "유효하지 않은 혜택이에요"}


@dataclass
class SelectedBenefits:
    ids: list[str]
    user_coupon: Optional[models.UserCoupon] = None
    coupon: Optional[models.Coupon] = None
    coupon_discount: int = 0
    user_pass: Optional[models.UserPass] = None
    pass_row: Optional[models.Pass] = None
    pass_discount: int = 0

    @property
    def total_discount(self) -> int:
        return self.coupon_discount + self.pass_discount


def _coupon_benefit(
    user_coupon: models.UserCoupon,
    coupon: models.Coupon,
    amount: int,
) -> Optional[schemas.BenefitItem]:
    if coupon.type == "time_limited":
        return None

    kind = "coupon_rate" if coupon.type == "discount_rate" else "coupon_amount"
    title = f"{coupon.value}% 할인 쿠폰" if coupon.type == "discount_rate" else f"{coupon.value:,}원 할인 쿠폰"
    if coupon.type == "discount_rate":
        desc = f"발급 매장 전용 · 최대 {coupon.max_discount:,}원" if coupon.max_discount else "발급 매장 전용"
    else:
        desc = f"{coupon.min_payment:,}원 이상 · 발급 매장 전용" if coupon.min_payment > 0 else "발급 매장 전용"

    benefit_id = f"coupon:{user_coupon.id}"
    if amount < coupon.min_payment:
        return schemas.BenefitItem(
            benefit_id=benefit_id,
            kind=kind,
            title=title,
            desc=desc,
            discount=0,
            selectable=False,
            reason=f"{coupon.min_payment:,}원 이상부터 사용 가능",
        )

    reason = None
    if coupon.type == "discount_rate":
        raw = round(amount * coupon.value / 100)
        discount = min(raw, coupon.max_discount) if coupon.max_discount is not None else raw
        if coupon.max_discount is not None and raw > coupon.max_discount:
            reason = f"최대 {coupon.max_discount:,}원 적용"
    else:
        discount = min(coupon.value, amount)

    return schemas.BenefitItem(
        benefit_id=benefit_id,
        kind=kind,
        title=title,
        desc=desc,
        discount=discount,
        selectable=True,
        reason=reason,
    )


def _pass_applies(
    user_pass: models.UserPass,
    pass_row: models.Pass,
    store: models.Store,
) -> bool:
    scope = user_pass.scope_snapshot or pass_row.scope
    scope_category = user_pass.scope_category_snapshot or pass_row.scope_category
    scope_store_id = user_pass.scope_store_id_snapshot or pass_row.scope_store_id
    if scope == "all":
        return True
    if scope == "category":
        return scope_category == store.category
    if scope == "store":
        return scope_store_id == store.id
    return False


def _pass_remaining(user_pass: models.UserPass, pass_row: models.Pass) -> Optional[int]:
    limit = user_pass.discount_limit
    if limit is None:
        limit = pass_row.max_discount_amount
    return max(limit - user_pass.discount_used, 0) if limit is not None else None


def _pass_desc(user_pass: models.UserPass, pass_row: models.Pass, store: models.Store) -> str:
    scope = user_pass.scope_snapshot or pass_row.scope
    discount_rate = user_pass.discount_rate_snapshot or pass_row.discount_rate
    if scope == "all":
        return f"모든 매장 {discount_rate}% 할인"
    if scope == "category":
        return f"{store.category} 매장 {discount_rate}% 할인"
    return f"이 매장 전용 {discount_rate}% 할인"


def _pass_benefit(
    user_pass: models.UserPass,
    pass_row: models.Pass,
    store: models.Store,
    amount: int,
) -> schemas.BenefitItem:
    remaining = _pass_remaining(user_pass, pass_row)
    discount_rate = user_pass.discount_rate_snapshot or pass_row.discount_rate
    raw_discount = round(amount * discount_rate / 100)
    discount = min(raw_discount, remaining) if remaining is not None else raw_discount
    selectable = remaining is None or remaining > 0
    return schemas.BenefitItem(
        benefit_id=f"pass:{user_pass.id}",
        kind="pass",
        title=user_pass.name_snapshot or pass_row.name,
        desc=_pass_desc(user_pass, pass_row, store),
        discount=discount if selectable else 0,
        selectable=selectable,
        reason=None if selectable else "누적 할인 한도를 모두 사용했어요",
        remaining_discount=remaining,
    )


def _benefit_ids(benefit_id: Optional[str], benefit_ids: list[str]) -> list[str]:
    selected = list(dict.fromkeys(benefit_ids)) if benefit_ids else [benefit_id or "none"]
    if not selected:
        return ["none"]
    if "none" in selected and len(selected) > 1:
        raise HTTPException(status_code=400, detail=INVALID_BENEFIT_ERROR)
    if len(selected) > 2:
        raise HTTPException(status_code=400, detail=INVALID_BENEFIT_ERROR)
    return sorted(selected, key=lambda value: (0 if value.startswith("coupon:") else 1))


def _resolve_benefits(
    db: Session,
    *,
    user_id: int,
    store: models.Store,
    amount: int,
    benefit_id: Optional[str],
    benefit_ids: list[str],
) -> SelectedBenefits:
    selected = SelectedBenefits(ids=_benefit_ids(benefit_id, benefit_ids))
    if selected.ids == ["none"]:
        return selected

    for item_id in selected.ids:
        if item_id.startswith("coupon:"):
            if selected.user_coupon is not None:
                raise HTTPException(status_code=400, detail=INVALID_BENEFIT_ERROR)
            try:
                row_id = int(item_id.split(":", 1)[1])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=INVALID_BENEFIT_ERROR) from exc
            user_coupon = db.get(models.UserCoupon, row_id)
            if (
                user_coupon is None
                or user_coupon.user_id != user_id
                or user_coupon.deleted_at is not None
            ):
                raise HTTPException(status_code=400, detail={"error": "coupon_unavailable", "message": "보유한 쿠폰을 찾을 수 없어요"})
            coupon = db.get(models.Coupon, user_coupon.coupon_id)
            sync_user_coupon_status(db, user_coupon, coupon)
            if user_coupon.status != "active":
                raise HTTPException(status_code=400, detail={"error": "coupon_unavailable", "message": "사용할 수 없는 쿠폰이에요"})
            if coupon.store_only and coupon.store_id != store.id:
                raise HTTPException(status_code=400, detail={"error": "coupon_unavailable", "message": "이 매장에서 사용할 수 없는 쿠폰이에요"})
            benefit = _coupon_benefit(user_coupon, coupon, amount)
            if benefit is None or not benefit.selectable:
                message = benefit.reason if benefit is not None else "사용할 수 없는 쿠폰이에요"
                raise HTTPException(status_code=400, detail={"error": "coupon_unavailable", "message": message})
            selected.user_coupon = user_coupon
            selected.coupon = coupon
            selected.coupon_discount = benefit.discount
            continue

        if item_id.startswith("pass:"):
            if selected.user_pass is not None:
                raise HTTPException(status_code=400, detail=INVALID_BENEFIT_ERROR)
            try:
                row_id = int(item_id.split(":", 1)[1])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=INVALID_BENEFIT_ERROR) from exc
            user_pass = db.get(models.UserPass, row_id)
            if user_pass is None or user_pass.user_id != user_id:
                raise HTTPException(status_code=400, detail={"error": "pass_unavailable", "message": "보유한 패스를 찾을 수 없어요"})
            sync_user_pass_status(db, user_pass)
            pass_row = db.get(models.Pass, user_pass.pass_id)
            if pass_row is None or user_pass.status != "active" or not _pass_applies(user_pass, pass_row, store):
                raise HTTPException(status_code=400, detail={"error": "pass_unavailable", "message": "이 매장에서 사용할 수 없는 패스예요"})
            benefit = _pass_benefit(user_pass, pass_row, store, amount)
            if not benefit.selectable:
                raise HTTPException(status_code=400, detail={"error": "pass_limit_exhausted", "message": benefit.reason})
            selected.user_pass = user_pass
            selected.pass_row = pass_row
            selected.pass_discount = min(benefit.discount, amount - selected.coupon_discount)
            continue

        raise HTTPException(status_code=400, detail=INVALID_BENEFIT_ERROR)

    return selected


@router.get("/checkout/benefits", response_model=schemas.CheckoutBenefitsResponse)
def get_checkout_benefits(
    store_id: int,
    amount: int,
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    store = db.get(models.Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail=STORE_NOT_FOUND_ERROR)

    benefits: list[schemas.BenefitItem] = []
    user_coupons = (
        db.query(models.UserCoupon)
        .filter(
            models.UserCoupon.user_id == x_user_id,
            models.UserCoupon.status == "active",
            models.UserCoupon.deleted_at.is_(None),
        )
        .all()
    )
    for user_coupon in user_coupons:
        coupon = db.get(models.Coupon, user_coupon.coupon_id)
        sync_user_coupon_status(db, user_coupon, coupon)
        if user_coupon.status != "active" or (coupon.store_only and coupon.store_id != store_id):
            continue
        benefit = _coupon_benefit(user_coupon, coupon, amount)
        if benefit is not None:
            benefits.append(benefit)

    user_passes = (
        db.query(models.UserPass)
        .filter(models.UserPass.user_id == x_user_id, models.UserPass.status == "active")
        .all()
    )
    for user_pass in user_passes:
        sync_user_pass_status(db, user_pass)
        pass_row = db.get(models.Pass, user_pass.pass_id)
        if pass_row is not None and user_pass.status == "active" and _pass_applies(user_pass, pass_row, store):
            benefits.append(_pass_benefit(user_pass, pass_row, store, amount))

    benefits.append(
        schemas.BenefitItem(
            benefit_id="none",
            kind="none",
            title="사용 안함",
            desc="원가 그대로 결제",
            discount=0,
            selectable=True,
        )
    )
    return schemas.CheckoutBenefitsResponse(store_name=store.name, amount=amount, benefits=benefits)


@router.post("/checkout/quote", response_model=schemas.CheckoutQuoteResponse)
def quote_checkout(
    payload: schemas.CheckoutQuoteRequest,
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail={"error": "invalid_payment_amount", "message": "주문 금액은 0원보다 커야 해요"})
    store = db.get(models.Store, payload.store_id)
    if store is None:
        raise HTTPException(status_code=404, detail=STORE_NOT_FOUND_ERROR)
    selected = _resolve_benefits(
        db,
        user_id=x_user_id,
        store=store,
        amount=payload.amount,
        benefit_id=payload.benefit_id,
        benefit_ids=payload.benefit_ids,
    )
    return schemas.CheckoutQuoteResponse(
        store_name=store.name,
        amount=payload.amount,
        total_discount=selected.total_discount,
        final_amount=payload.amount - selected.total_discount,
        benefit_ids=selected.ids,
    )


def _validate_qr(
    db: Session,
    *,
    qr_token: Optional[str],
    user_id: int,
    store_id: int,
    amount: int,
) -> Optional[models.PaymentQr]:
    if not qr_token:
        return None
    qr = db.query(models.PaymentQr).filter(models.PaymentQr.token == qr_token).first()
    if qr is None or qr.type != "payment":
        raise HTTPException(status_code=400, detail={"error": "invalid_qr", "message": "유효하지 않은 QR이에요"})
    now = utc_now()
    if qr.expires_at is not None and now > qr.expires_at:
        qr.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=410, detail={"error": "expired_qr", "message": "만료된 QR이에요"})
    if qr.status == "CONSUMED":
        raise HTTPException(status_code=409, detail={"error": "already_used", "message": "이미 처리된 QR이에요"})
    if qr.status == "SCANNED" and qr.consumed_by != user_id:
        raise HTTPException(status_code=409, detail={"error": "qr_in_use", "message": "다른 사용자가 결제를 진행 중인 QR이에요"})
    if qr.store_id != store_id or qr.amount != amount:
        raise HTTPException(status_code=400, detail={"error": "qr_payment_mismatch", "message": "QR의 매장 또는 결제 금액이 요청과 일치하지 않아요"})
    if qr.status == "WAITING":
        qr.status = "SCANNED"
        qr.scanned_at = now
        qr.consumed_by = user_id
    return qr


@router.post("/checkout")
def do_checkout(
    payload: schemas.CheckoutRequest,
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    store = db.get(models.Store, payload.store_id)
    if store is None:
        raise HTTPException(status_code=404, detail=STORE_NOT_FOUND_ERROR)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail={"error": "invalid_payment_amount", "message": "주문 금액은 0원보다 커야 해요"})

    if payload.paymentKey and payload.orderId and payload.payment_amount is not None and payload.payment_amount > 0:
        cached = completed_result_or_conflict(
            db,
            payment_key=payload.paymentKey,
            order_id=payload.orderId,
            user_id=x_user_id,
            purpose="checkout",
            amount=payload.payment_amount,
        )
        if cached is not None:
            return cached

    qr = _validate_qr(
        db,
        qr_token=payload.qr_token,
        user_id=x_user_id,
        store_id=payload.store_id,
        amount=payload.amount,
    )
    selected = _resolve_benefits(
        db,
        user_id=x_user_id,
        store=store,
        amount=payload.amount,
        benefit_id=payload.benefit_id,
        benefit_ids=payload.benefit_ids,
    )
    final_amount = payload.amount - selected.total_discount

    confirmed = None
    if final_amount > 0:
        if not payload.paymentKey or not payload.orderId or payload.payment_amount is None:
            db.rollback()
            raise HTTPException(status_code=400, detail={"error": "payment_info_required", "message": "실제 결제 금액이 있으면 토스 결제 정보를 모두 전달해야 해요"})
        if payload.payment_amount != final_amount:
            db.rollback()
            raise HTTPException(status_code=400, detail={"error": "payment_amount_mismatch", "message": "결제 금액이 서버에서 계산한 최종 금액과 일치하지 않아요"})
        try:
            confirmed = confirm_toss_payment(payload.paymentKey, payload.orderId, payload.payment_amount)
        except Exception:
            db.rollback()
            raise

    try:
        now = utc_now()
        applied_benefits: list[dict] = []
        if selected.user_coupon is not None and selected.coupon is not None:
            selected.user_coupon.status = "used"
            selected.user_coupon.used_at = now
            db.add(
                models.Transaction(
                    user_id=x_user_id,
                    type="coupon_use",
                    store_name=store.name,
                    store_id=store.id,
                    amount=-selected.coupon_discount,
                    memo=selected.coupon.title,
                    created_at=now,
                )
            )
            applied_benefits.append(
                {
                    "kind": (
                        "coupon_rate"
                        if selected.coupon.type == "discount_rate"
                        else "coupon_amount"
                    ),
                    "name": selected.coupon.title,
                    "discount": selected.coupon_discount,
                }
            )

        if selected.user_pass is not None and selected.pass_row is not None:
            selected.user_pass.discount_used += selected.pass_discount
            db.add(
                models.Transaction(
                    user_id=x_user_id,
                    type="pass_use",
                    store_name=store.name,
                    store_id=store.id,
                    amount=-selected.pass_discount,
                    memo=selected.user_pass.name_snapshot or selected.pass_row.name,
                    discount_rate=(
                        selected.user_pass.discount_rate_snapshot
                        or selected.pass_row.discount_rate
                    ),
                    created_at=now,
                )
            )
            applied_benefits.append(
                {
                    "kind": "pass",
                    "name": selected.user_pass.name_snapshot or selected.pass_row.name,
                    "discount": selected.pass_discount,
                }
            )

        benefit_applied = " + ".join(
            f"{item['name']} (-{item['discount']:,}원)" for item in applied_benefits
        ) or None
        payment = models.Payment(
            store_id=store.id,
            qr_id=qr.id if qr is not None else None,
            amount=final_amount,
            status="DONE",
            original_amount=payload.amount,
            discount_amount=selected.total_discount,
            benefit_summary=benefit_applied,
            completed_at=now,
        )
        db.add(payment)
        db.flush()

        if qr is not None:
            qr.status = "CONSUMED"
            qr.consumed_at = now

        stamp_result = None
        policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
        if policy is not None and policy.active and payload.amount >= policy.min_amount:
            from app.routers.stamps import _earn_stamp, stamped_today

            if stamped_today(db, x_user_id, now):
                stamp_result = {"earned": False, "reason": "daily_limit"}
            else:
                stamp_card = (
                    db.query(models.StampCard)
                    .filter(
                        models.StampCard.user_id == x_user_id,
                        models.StampCard.store_id == store.id,
                    )
                    .first()
                )
                if (
                    policy.completion_limit is not None
                    and stamp_card is not None
                    and stamp_card.completed_count >= policy.completion_limit
                ):
                    stamp_result = {"earned": False, "reason": "completion_limit"}
                else:
                    stamp_result = {
                        "earned": True,
                        **_earn_stamp(db, x_user_id, store, now, amount=payload.amount),
                    }

        payment_status = confirmed["status"] if confirmed is not None else "NOT_REQUIRED"
        kinds = [item["kind"] for item in applied_benefits]
        benefit_kind = "+".join(kinds) if kinds else "none"
        result = {
            "result": "success",
            "store_name": store.name,
            "benefit_applied": benefit_applied,
            "applied_benefits": applied_benefits,
            "final_amount": final_amount,
            "benefit_kind": benefit_kind,
            "consumed": selected.user_coupon is not None,
            "payment_id": payment.id,
            "payment_key": payload.paymentKey,
            "order_id": payload.orderId,
            "payment_status": payment_status,
            "stamp": stamp_result,
            "message": "결제가 완료됐어요",
        }

        if confirmed is not None:
            db.add(
                models.TossPayment(
                    payment_key=payload.paymentKey,
                    order_id=payload.orderId,
                    user_id=x_user_id,
                    purpose="checkout",
                    amount=payload.payment_amount,
                    status=payment_status,
                    method=confirmed.get("method") or payload.method,
                    store_id=store.id,
                    checkout_payment_id=payment.id,
                    result_json=json.dumps(jsonable_encoder(result), ensure_ascii=False),
                    approved_at=now,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if confirmed is not None:
            cached = completed_result_or_conflict(
                db,
                payment_key=payload.paymentKey,
                order_id=payload.orderId,
                user_id=x_user_id,
                purpose="checkout",
                amount=payload.payment_amount,
            )
            if cached is not None:
                return cached
        raise HTTPException(status_code=409, detail={"error": "payment_already_processed", "message": "이미 처리된 결제예요"}) from exc
    except Exception:
        db.rollback()
        raise

    return result
