from math import asin, cos, radians, sin, sqrt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import get_optional_user_id, utc_now

router = APIRouter(tags=["stores"])


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


@router.get("/stores", response_model=schemas.StoreListResponse)
def list_stores(
    region: Optional[str] = Query(default=None),
    category: str = Query(default="all"),
    sort: str = Query(default="popular"),
    q: Optional[str] = Query(default=None),
    latitude: Optional[float] = Query(default=None),
    longitude: Optional[float] = Query(default=None),
    radius_km: float = Query(default=5.0, gt=0, le=30),
    x_user_id: Optional[int] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(models.Store)
    if region:
        query = query.filter(models.Store.region == region)
    if category and category != "all":
        query = query.filter(models.Store.category == category)
    if q and q.strip():
        query = query.filter(models.Store.name.ilike(f"%{q.strip()}%"))

    if sort == "recent":
        query = query.order_by(models.Store.id.desc())
    else:
        query = query.order_by(models.Store.id.asc())

    stores_with_distance: list[tuple[models.Store, Optional[float]]] = []
    for store in query.all():
        distance = None
        if latitude is not None and longitude is not None and store.latitude is not None and store.longitude is not None:
            distance = _distance_km(latitude, longitude, store.latitude, store.longitude)
            if distance > radius_km:
                continue
        stores_with_distance.append((store, distance))
    if sort == "distance" and latitude is not None and longitude is not None:
        stores_with_distance.sort(key=lambda item: item[1] if item[1] is not None else float("inf"))

    cards_by_store_id = {}
    if x_user_id is not None:
        cards = (
            db.query(models.StampCard)
            .filter(models.StampCard.user_id == x_user_id)
            .all()
        )
        cards_by_store_id = {card.store_id: card for card in cards}

    items: list[schemas.StoreListItem] = []
    for store, distance in stores_with_distance:
        card = cards_by_store_id.get(store.id)
        stamp_summary = None
        if card is not None:
            policy = (
                db.query(models.StampPolicy)
                .filter(models.StampPolicy.store_id == store.id, models.StampPolicy.active.is_(True))
                .first()
            )
            if policy is not None:
                stamp_summary = schemas.StampSummary(current=card.current, goal=policy.goal)
        items.append(
            schemas.StoreListItem(
                id=store.id,
                name=store.name,
                category=store.category,
                region=store.region,
                address=store.address,
                image_url=store.image_url,
                latitude=store.latitude,
                longitude=store.longitude,
                distance_km=round(distance, 2) if distance is not None else None,
                stamp_summary=stamp_summary,
            )
        )

    return schemas.StoreListResponse(stores=items)


@router.get("/stores/{store_id}", response_model=schemas.StoreDetailResponse)
def get_store(
    store_id: int,
    x_user_id: Optional[int] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    store = db.get(models.Store, store_id)
    if store is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "store_not_found", "message": "매장을 찾을 수 없어요"},
        )

    policy = (
        db.query(models.StampPolicy)
        .filter(models.StampPolicy.store_id == store.id, models.StampPolicy.active.is_(True))
        .first()
    )

    current = 0
    has_stamped_today = False
    if x_user_id is not None:
        card = (
            db.query(models.StampCard)
            .filter(models.StampCard.user_id == x_user_id, models.StampCard.store_id == store.id)
            .first()
        )
        if card is not None:
            current = card.current
        from app.routers.stamps import stamped_today

        has_stamped_today = stamped_today(db, x_user_id)

    claimed_coupon_ids: set[int] = set()
    if x_user_id is not None:
        claimed_coupon_ids = {
            row.coupon_id
            for row in db.query(models.UserCoupon).filter(models.UserCoupon.user_id == x_user_id).all()
        }
    now = utc_now()
    coupon_rows = (
        db.query(models.Coupon)
        .filter(
            models.Coupon.store_id == store.id,
            models.Coupon.status == "active",
            models.Coupon.source == "owner",
        )
        .order_by(models.Coupon.id.desc())
        .all()
    )
    coupons = [
        schemas.StoreCouponSummary(
            id=coupon.id,
            type=coupon.type,
            title=coupon.title,
            value=coupon.value,
            valid_until=coupon.valid_until,
            claimed_by_me=coupon.id in claimed_coupon_ids,
        )
        for coupon in coupon_rows
        if coupon.valid_until is None or coupon.valid_until >= now
    ]

    return schemas.StoreDetailResponse(
        id=store.id,
        name=store.name,
        category=store.category,
        region=store.region,
        business_hours=store.business_hours,
        address=store.address,
        phone_no=store.phone_no,
        image_url=store.image_url,
        latitude=store.latitude,
        longitude=store.longitude,
        stamp=(
            schemas.StoreDetailStamp(
                goal=policy.goal,
                current=current,
                reward=policy.reward,
                condition=policy.condition,
                stamped_today=has_stamped_today,
            )
            if policy
            else None
        ),
        coupons=coupons,
    )
