import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import get_optional_user_id, utc_now

router = APIRouter(tags=["stores"])


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """? GPS ?? ??? ??? ?? ??? ????."""
    radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lam = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lam / 2) ** 2
    return round(radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _store_item(store: models.Store, stamp_summary: schemas.StampSummary | None, distance_m: int | None = None):
    return schemas.StoreListItem(
        id=store.id,
        name=store.name,
        category=store.category,
        region=store.region,
        address=store.address,
        phone_no=store.phone_no,
        latitude=store.latitude,
        longitude=store.longitude,
        image_url=store.image_url,
        distance_m=distance_m,
        stamp_summary=stamp_summary,
    )


@router.get("/stores", response_model=schemas.StoreListResponse)
def list_stores(
    region: Optional[str] = Query(default=None),
    category: str = Query(default="all"),
    sort: str = Query(default="popular"),
    q: Optional[str] = Query(default=None, description="매장명 검색어"),
    latitude: Optional[float] = Query(default=None, ge=-90, le=90),
    longitude: Optional[float] = Query(default=None, ge=-180, le=180),
    lat: Optional[float] = Query(default=None, ge=-90, le=90),
    lng: Optional[float] = Query(default=None, ge=-180, le=180),
    radius_km: Optional[float] = Query(default=None, gt=0),
    x_user_id: Optional[int] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    """?? ??/?? API.

    - ?? ??? ??? ???? `latitude`/`longitude` ?? `lat`/`lng`? ???
      ??? `distance_m`? ???? ??? ??? ????.
    - `radius_km`? ?? ??? ?? ?? ?? ?? ?? ??? ????.
    - ?? ??? ??? ???? ?? ?? ???? ???? ??/??/???? ??? ????.
    """
    user_lat = latitude if latitude is not None else lat
    user_lng = longitude if longitude is not None else lng

    query = db.query(models.Store)
    if region:
        query = query.filter(models.Store.region == region)
    if category and category != "all":
        query = query.filter(models.Store.category == category)
    if q and q.strip():
        query = query.filter(models.Store.name.contains(q.strip()))

    if sort == "recent":
        query = query.order_by(models.Store.id.desc())
    else:
        query = query.order_by(models.Store.id.asc())

    stores = query.all()

    cards_by_store_id = {}
    if x_user_id is not None:
        cards = (
            db.query(models.StampCard)
            .filter(models.StampCard.user_id == x_user_id)
            .all()
        )
        cards_by_store_id = {card.store_id: card for card in cards}

    items: list[schemas.StoreListItem] = []
    for store in stores:
        distance = None
        if user_lat is not None and user_lng is not None and store.latitude is not None and store.longitude is not None:
            distance = _distance_m(user_lat, user_lng, store.latitude, store.longitude)
            if radius_km is not None and distance > radius_km * 1000:
                continue

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
        items.append(_store_item(store, stamp_summary, distance))

    if user_lat is not None and user_lng is not None:
        items.sort(key=lambda item: item.distance_m if item.distance_m is not None else 10**12)

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
