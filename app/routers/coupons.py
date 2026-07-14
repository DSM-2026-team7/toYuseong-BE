from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import (
    compute_d_day,
    get_optional_user_id,
    iso_z,
    require_user_id,
    sync_user_coupon_status,
    utc_now,
)

router = APIRouter(tags=["coupons"])

COUPON_NOT_FOUND_ERROR = {"error": "coupon_not_found", "message": "쿠폰을 찾을 수 없어요"}
ALREADY_CLAIMED_ERROR = {"error": "already_claimed", "message": "이미 받은 쿠폰이에요"}
COUPON_EXPIRED_ERROR = {"error": "coupon_expired", "message": "발급이 종료된 쿠폰이에요"}
USER_COUPON_NOT_FOUND_ERROR = {"error": "user_coupon_not_found", "message": "보유한 쿠폰을 찾을 수 없어요"}


def _coupon_list_item(coupon: models.Coupon, store: models.Store, claimed_by_me: bool) -> schemas.CouponListItem:
    is_time_limited = coupon.type == "time_limited"
    return schemas.CouponListItem(
        id=coupon.id,
        store_name=store.name,
        type=coupon.type,
        title=coupon.title,
        value=coupon.value,
        target=coupon.target,
        valid_until=None if is_time_limited else coupon.valid_until,
        d_day=None if is_time_limited else compute_d_day(coupon.valid_until),
        time_limit_hours=coupon.time_limit_hours if is_time_limited else None,
        store_only=coupon.store_only,
        claimed_by_me=claimed_by_me,
    )


@router.get("/coupons", response_model=schemas.CouponListResponse)
def list_coupons(
    region: Optional[str] = Query(default=None),
    category: str = Query(default="all"),
    sort: str = Query(default="popular"),
    x_user_id: Optional[int] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(models.Coupon).join(models.Store, models.Coupon.store_id == models.Store.id)
    if region:
        query = query.filter(models.Store.region == region)
    if category and category != "all":
        query = query.filter(models.Store.category == category)

    if sort == "recent":
        query = query.order_by(models.Coupon.id.desc())
    else:
        query = query.order_by(models.Coupon.id.asc())

    coupons = query.all()

    claimed_coupon_ids: set[int] = set()
    if x_user_id is not None:
        claimed_coupon_ids = {
            row.coupon_id
            for row in db.query(models.UserCoupon.coupon_id)
            .filter(models.UserCoupon.user_id == x_user_id)
            .all()
        }

    items = [
        _coupon_list_item(coupon, db.get(models.Store, coupon.store_id), coupon.id in claimed_coupon_ids)
        for coupon in coupons
    ]

    return schemas.CouponListResponse(coupons=items)


@router.post("/coupons/{coupon_id}/claim", response_model=schemas.ClaimResponse, status_code=201)
def claim_coupon(coupon_id: int, x_user_id: int = Depends(require_user_id), db: Session = Depends(get_db)):
    coupon = db.get(models.Coupon, coupon_id)
    if coupon is None:
        raise HTTPException(status_code=404, detail=COUPON_NOT_FOUND_ERROR)

    already_claimed = (
        db.query(models.UserCoupon)
        .filter(models.UserCoupon.user_id == x_user_id, models.UserCoupon.coupon_id == coupon_id)
        .first()
    )
    if already_claimed is not None:
        raise HTTPException(status_code=409, detail=ALREADY_CLAIMED_ERROR)

    now = utc_now()
    if coupon.type != "time_limited" and coupon.valid_until is not None and now > coupon.valid_until:
        raise HTTPException(status_code=410, detail=COUPON_EXPIRED_ERROR)

    user_coupon = models.UserCoupon(
        user_id=x_user_id,
        coupon_id=coupon.id,
        status="active",
        claimed_at=now,
        used_at=None,
        expired_at=None,
    )
    db.add(user_coupon)
    db.flush()

    store = db.get(models.Store, coupon.store_id)
    db.add(
        models.Transaction(
            user_id=x_user_id,
            type="coupon_claim",
            store_name=store.name,
            amount=None,
            memo=coupon.title,
            created_at=now,
        )
    )
    db.commit()

    return schemas.ClaimResponse(
        user_coupon_id=user_coupon.id,
        coupon_id=coupon.id,
        status="active",
        claimed_at=now,
        message="쿠폰함에 담겼어요",
    )


def _my_coupon_item(
    user_coupon: models.UserCoupon, coupon: models.Coupon, store: models.Store
) -> schemas.MyCouponItem:
    is_time_limited = coupon.type == "time_limited"
    return schemas.MyCouponItem(
        user_coupon_id=user_coupon.id,
        store_name=store.name,
        type=coupon.type,
        title=coupon.title,
        value=coupon.value,
        status=user_coupon.status,
        claimed_at=user_coupon.claimed_at,
        used_at=user_coupon.used_at,
        expired_at=user_coupon.expired_at,
        valid_until=None if is_time_limited else coupon.valid_until,
        d_day=None if is_time_limited else compute_d_day(coupon.valid_until),
    )


@router.get("/me/coupons", response_model=schemas.MyCouponListResponse)
def list_my_coupons(
    status: str = Query(default="active"),
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    user_coupons = db.query(models.UserCoupon).filter(models.UserCoupon.user_id == x_user_id).all()

    items: list[schemas.MyCouponItem] = []
    for user_coupon in user_coupons:
        coupon = db.get(models.Coupon, user_coupon.coupon_id)
        sync_user_coupon_status(db, user_coupon, coupon)
        if status != "all" and user_coupon.status != status:
            continue
        store = db.get(models.Store, coupon.store_id)
        items.append(_my_coupon_item(user_coupon, coupon, store))

    items.sort(key=lambda item: item.claimed_at, reverse=True)
    return schemas.MyCouponListResponse(coupons=items)


@router.get("/me/coupons/{user_coupon_id}", response_model=schemas.CouponDetailResponse)
def get_my_coupon(user_coupon_id: int, x_user_id: int = Depends(require_user_id), db: Session = Depends(get_db)):
    user_coupon = db.get(models.UserCoupon, user_coupon_id)
    if user_coupon is None or user_coupon.user_id != x_user_id:
        raise HTTPException(status_code=404, detail=USER_COUPON_NOT_FOUND_ERROR)

    coupon = db.get(models.Coupon, user_coupon.coupon_id)
    sync_user_coupon_status(db, user_coupon, coupon)
    store = db.get(models.Store, coupon.store_id)

    is_time_limited = coupon.type == "time_limited"
    return schemas.CouponDetailResponse(
        user_coupon_id=user_coupon.id,
        store=schemas.CouponDetailStore(
            name=store.name,
            category=store.category,
            region=store.region,
            business_hours=store.business_hours,
        ),
        type=coupon.type,
        title=coupon.title,
        value=coupon.value,
        target=coupon.target,
        status=user_coupon.status,
        used_at=user_coupon.used_at,
        expired_at=user_coupon.expired_at,
        valid_until=None if is_time_limited else coupon.valid_until,
        d_day=None if is_time_limited else compute_d_day(coupon.valid_until),
        store_only=coupon.store_only,
        usage_note="발급 매장에서만 사용 가능" if coupon.store_only else "유성구 전 매장에서 사용 가능",
    )


@router.post("/me/coupons/{user_coupon_id}/use", response_model=schemas.UseCouponResponse)
def use_coupon(user_coupon_id: int, x_user_id: int = Depends(require_user_id), db: Session = Depends(get_db)):
    user_coupon = db.get(models.UserCoupon, user_coupon_id)
    if user_coupon is None or user_coupon.user_id != x_user_id:
        raise HTTPException(status_code=404, detail=USER_COUPON_NOT_FOUND_ERROR)

    coupon = db.get(models.Coupon, user_coupon.coupon_id)
    sync_user_coupon_status(db, user_coupon, coupon)

    if user_coupon.status == "used":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_used",
                "message": "이미 사용된 쿠폰이에요",
                "used_at": iso_z(user_coupon.used_at),
            },
        )
    if user_coupon.status == "expired":
        raise HTTPException(
            status_code=410,
            detail={
                "error": "coupon_expired",
                "message": "기간이 만료된 쿠폰이에요",
                "expired_at": iso_z(user_coupon.expired_at),
            },
        )

    now = utc_now()
    user_coupon.status = "used"
    user_coupon.used_at = now

    store = db.get(models.Store, coupon.store_id)
    db.add(
        models.Transaction(
            user_id=x_user_id,
            type="coupon_use",
            store_name=store.name,
            amount=None,
            memo=coupon.title,
            created_at=now,
        )
    )
    db.commit()

    return schemas.UseCouponResponse(
        user_coupon_id=user_coupon.id,
        status="used",
        used_at=now,
        message="쿠폰이 사용되었어요",
    )
