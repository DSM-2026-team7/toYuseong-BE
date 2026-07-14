from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import require_user_id, sync_user_coupon_status, sync_user_pass_status, utc_now

router = APIRouter(tags=["checkout"])

STORE_NOT_FOUND_ERROR = {"error": "store_not_found", "message": "매장을 찾을 수 없어요"}


def _coupon_benefit(user_coupon: models.UserCoupon, coupon: models.Coupon, amount: int) -> Optional[schemas.BenefitItem]:
    """coupon.type==time_limited은 결제 할인 혜택이 아니므로 목록에서 제외한다(None)."""
    if coupon.type == "time_limited":
        return None

    kind = "coupon_rate" if coupon.type == "discount_rate" else "coupon_amount"
    title = f"{coupon.value}% 할인 쿠폰" if coupon.type == "discount_rate" else f"{coupon.value:,}원 할인 쿠폰"

    if coupon.type == "discount_rate":
        desc = f"이 매장 발급분 · 최대 {coupon.max_discount:,}원" if coupon.max_discount else "이 매장 발급분"
    else:
        desc = f"{coupon.min_payment:,}원 이상 · 이 매장 발급분" if coupon.min_payment > 0 else "이 매장 발급분"

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
        if coupon.max_discount is not None and raw > coupon.max_discount:
            discount = coupon.max_discount
            reason = f"최대 {coupon.max_discount:,}원 적용"
        else:
            discount = raw
    else:
        discount = min(coupon.value, amount)

    return schemas.BenefitItem(
        benefit_id=benefit_id, kind=kind, title=title, desc=desc, discount=discount, selectable=True, reason=reason
    )


def _pass_applies(pass_row: models.Pass, store: models.Store) -> bool:
    if pass_row.scope == "all":
        return True
    if pass_row.scope == "category":
        return pass_row.scope_category == store.category
    if pass_row.scope == "store":
        return pass_row.scope_store_id == store.id
    return False


def _pass_desc(pass_row: models.Pass, store: models.Store) -> str:
    if pass_row.scope == "all":
        return f"모든 매장 {pass_row.discount_rate}% 할인 · 보유 패스"
    if pass_row.scope == "category":
        return f"{store.category} {pass_row.discount_rate}% 할인 · 보유 패스 · 전 매장 공통"
    return f"이 매장 전용 · {pass_row.discount_rate}% 할인 · 보유 패스"


def _pass_benefit(user_pass: models.UserPass, pass_row: models.Pass, store: models.Store, amount: int) -> schemas.BenefitItem:
    discount = round(amount * pass_row.discount_rate / 100)
    return schemas.BenefitItem(
        benefit_id=f"pass:{user_pass.id}",
        kind="pass",
        title=pass_row.name,
        desc=_pass_desc(pass_row, store),
        discount=discount,
        selectable=True,
        reason=None,
    )


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
        .filter(models.UserCoupon.user_id == x_user_id, models.UserCoupon.status == "active")
        .all()
    )
    for user_coupon in user_coupons:
        coupon = db.get(models.Coupon, user_coupon.coupon_id)
        sync_user_coupon_status(db, user_coupon, coupon)
        if user_coupon.status != "active":
            continue
        if coupon.store_only and coupon.store_id != store_id:
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
        if user_pass.status != "active":
            continue
        pass_row = db.get(models.Pass, user_pass.pass_id)
        if not _pass_applies(pass_row, store):
            continue
        benefits.append(_pass_benefit(user_pass, pass_row, store, amount))

    benefits.append(
        schemas.BenefitItem(
            benefit_id="none",
            kind="none",
            title="사용 안함",
            desc="원가 그대로 결제",
            discount=0,
            selectable=True,
            reason=None,
        )
    )

    return schemas.CheckoutBenefitsResponse(store_name=store.name, amount=amount, benefits=benefits)


@router.post("/checkout")
def do_checkout(payload: schemas.CheckoutRequest, x_user_id: int = Depends(require_user_id), db: Session = Depends(get_db)):
    store = db.get(models.Store, payload.store_id)
    if store is None:
        return {"result": "fail", "message": "매장을 찾을 수 없어요"}

    now = utc_now()

    if payload.benefit_id == "none":
        return {
            "result": "success",
            "store_name": store.name,
            "benefit_applied": None,
            "final_amount": payload.amount,
            "benefit_kind": "none",
            "consumed": False,
            "message": "결제가 완료됐어요",
        }

    if payload.benefit_id.startswith("coupon:"):
        try:
            user_coupon_id = int(payload.benefit_id.split(":", 1)[1])
        except ValueError:
            return {"result": "fail", "message": "유효하지 않은 혜택이에요"}

        user_coupon = db.get(models.UserCoupon, user_coupon_id)
        if user_coupon is None or user_coupon.user_id != x_user_id:
            return {"result": "fail", "message": "보유한 쿠폰을 찾을 수 없어요"}

        coupon = db.get(models.Coupon, user_coupon.coupon_id)
        sync_user_coupon_status(db, user_coupon, coupon)

        if user_coupon.status == "used":
            return {"result": "fail", "message": "이미 사용된 쿠폰이에요"}
        if user_coupon.status == "expired":
            return {"result": "fail", "message": "기간이 만료된 쿠폰이에요"}
        if coupon.store_only and coupon.store_id != store.id:
            return {"result": "fail", "message": "이 매장에서 사용할 수 없는 쿠폰이에요"}
        if payload.amount < coupon.min_payment:
            return {"result": "fail", "message": f"{coupon.min_payment:,}원 이상부터 사용 가능해요"}

        benefit = _coupon_benefit(user_coupon, coupon, payload.amount)
        if benefit is None:
            return {"result": "fail", "message": "사용할 수 없는 쿠폰이에요"}

        discount = benefit.discount
        final_amount = payload.amount - discount

        user_coupon.status = "used"
        user_coupon.used_at = now

        db.add(
            models.Transaction(
                user_id=x_user_id,
                type="coupon_use",
                store_name=store.name,
                amount=-discount,
                memo=None,
                created_at=now,
            )
        )
        db.commit()

        return {
            "result": "success",
            "store_name": store.name,
            "benefit_applied": f"{benefit.title} (-{discount:,}원)",
            "final_amount": final_amount,
            "benefit_kind": benefit.kind,
            "consumed": True,
            "message": "쿠폰이 사용 처리됐어요",
        }

    if payload.benefit_id.startswith("pass:"):
        try:
            user_pass_id = int(payload.benefit_id.split(":", 1)[1])
        except ValueError:
            return {"result": "fail", "message": "유효하지 않은 혜택이에요"}

        user_pass = db.get(models.UserPass, user_pass_id)
        if user_pass is None or user_pass.user_id != x_user_id:
            return {"result": "fail", "message": "보유한 패스를 찾을 수 없어요"}

        sync_user_pass_status(db, user_pass)
        if user_pass.status != "active":
            return {"result": "fail", "message": "기간이 만료된 패스예요"}

        pass_row = db.get(models.Pass, user_pass.pass_id)
        if not _pass_applies(pass_row, store):
            return {"result": "fail", "message": "이 매장에서 사용할 수 없는 패스예요"}

        discount = round(payload.amount * pass_row.discount_rate / 100)
        final_amount = payload.amount - discount

        db.add(
            models.Transaction(
                user_id=x_user_id,
                type="pass_use",
                store_name=store.name,
                amount=-discount,
                memo=None,
                created_at=now,
            )
        )
        db.commit()

        return {
            "result": "success",
            "store_name": store.name,
            "benefit_applied": f"{pass_row.name} (-{discount:,}원)",
            "final_amount": final_amount,
            "benefit_kind": "pass",
            "consumed": False,
            "message": "패스 할인이 적용됐어요",
        }

    return {"result": "fail", "message": "유효하지 않은 혜택이에요"}
