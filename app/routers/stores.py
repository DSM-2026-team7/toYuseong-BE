from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import utc_now

router = APIRouter(tags=["stores"])


def get_optional_user_id(
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
) -> Optional[int]:
    return x_user_id


@router.get("/stores", response_model=schemas.StoreListResponse)
def list_stores(
    region: Optional[str] = Query(default=None),
    category: str = Query(default="all"),
    sort: str = Query(default="popular"),
    x_user_id: Optional[int] = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(models.Store)
    if region:
        query = query.filter(models.Store.region == region)
    if category and category != "all":
        query = query.filter(models.Store.category == category)

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
        card = cards_by_store_id.get(store.id)
        stamp_summary = None
        if card is not None:
            policy = (
                db.query(models.StampPolicy)
                .filter(models.StampPolicy.store_id == store.id)
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
        .filter(models.StampPolicy.store_id == store.id)
        .first()
    )

    current = 0
    stamped_today = False
    if x_user_id is not None:
        card = (
            db.query(models.StampCard)
            .filter(models.StampCard.user_id == x_user_id, models.StampCard.store_id == store.id)
            .first()
        )
        if card is not None:
            current = card.current
            stamped_today = card.updated_at.date() == utc_now().date()

    return schemas.StoreDetailResponse(
        id=store.id,
        name=store.name,
        category=store.category,
        region=store.region,
        business_hours=store.business_hours,
        stamp=schemas.StoreDetailStamp(
            goal=policy.goal if policy else 0,
            current=current,
            reward=policy.reward if policy else "",
            condition=policy.condition if policy else "",
            stamped_today=stamped_today,
        ),
    )
