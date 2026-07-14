from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from web import schemas

router = APIRouter(prefix="/admin", tags=["admin-passes"])

NOT_FOUND = {"error": "pass_not_found", "message": "패스를 찾을 수 없어요"}


def _get_price_tiers(db: Session, pass_id: int) -> list[schemas.PassPriceTierItem]:
    tiers = (
        db.query(models.PassPriceTier)
        .filter(models.PassPriceTier.pass_id == pass_id)
        .order_by(models.PassPriceTier.duration_days)
        .all()
    )
    if tiers:
        return [schemas.PassPriceTierItem(duration_days=t.duration_days, price=t.price) for t in tiers]
    # PassPriceTier가 없으면 Pass 본체의 단일 값으로 폴백
    pass_row = db.get(models.Pass, pass_id)
    if pass_row:
        return [schemas.PassPriceTierItem(duration_days=pass_row.duration_days, price=pass_row.price)]
    return []


def _sync_primary_tier(pass_row: models.Pass, tiers: list[schemas.PassPriceTierItem]) -> None:
    """앱 API 호환: Pass 본체의 duration_days/price를 첫 번째 티어에 동기화."""
    if tiers:
        pass_row.duration_days = tiers[0].duration_days
        pass_row.price = tiers[0].price


@router.get("/passes", response_model=schemas.AdminPassListResponse)
def list_passes(db: Session = Depends(get_db)):
    passes = db.query(models.Pass).order_by(models.Pass.id).all()
    items = [
        schemas.AdminPassListItem(
            id=p.id,
            name=p.name,
            scope=p.scope,
            scope_category=p.scope_category,
            discount_rate=p.discount_rate,
            price_tiers=_get_price_tiers(db, p.id),
            sale_status=p.sale_status,
        )
        for p in passes
    ]
    return schemas.AdminPassListResponse(passes=items)


@router.get("/passes/{pass_id}", response_model=schemas.AdminPassDetailResponse)
def get_pass(pass_id: int, db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return schemas.AdminPassDetailResponse(
        id=pass_row.id,
        name=pass_row.name,
        scope=pass_row.scope,
        scope_category=pass_row.scope_category,
        scope_store_id=pass_row.scope_store_id,
        discount_rate=pass_row.discount_rate,
        target_desc=pass_row.target_desc,
        price_tiers=_get_price_tiers(db, pass_row.id),
        sale_status=pass_row.sale_status,
    )


@router.post("/passes", response_model=schemas.AdminPassResponse, status_code=201)
def create_pass(payload: schemas.AdminPassCreateRequest, db: Session = Depends(get_db)):
    first_tier = payload.price_tiers[0] if payload.price_tiers else None
    pass_row = models.Pass(
        name=payload.name,
        scope=payload.scope,
        period_type="period" if (first_tier and first_tier.duration_days > 1) else "one_day",
        duration_days=first_tier.duration_days if first_tier else 1,
        price=first_tier.price if first_tier else 0,
        discount_rate=payload.discount_rate,
        target_desc=payload.target_desc,
        scope_category=payload.scope_category,
        scope_store_id=payload.scope_store_id,
        sale_status=payload.sale_status,
    )
    db.add(pass_row)
    db.flush()

    for tier in payload.price_tiers:
        db.add(models.PassPriceTier(pass_id=pass_row.id, duration_days=tier.duration_days, price=tier.price))
    db.commit()

    return schemas.AdminPassResponse(id=pass_row.id, message=f"{pass_row.name}을(를) 등록했어요")


@router.put("/passes/{pass_id}", response_model=schemas.AdminPassResponse)
def update_pass(pass_id: int, payload: schemas.AdminPassUpdateRequest, db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)

    pass_row.name = payload.name
    pass_row.scope = payload.scope
    pass_row.scope_category = payload.scope_category
    pass_row.scope_store_id = payload.scope_store_id
    pass_row.discount_rate = payload.discount_rate
    pass_row.target_desc = payload.target_desc
    pass_row.sale_status = payload.sale_status

    # 기존 price tiers 삭제 후 재생성
    db.query(models.PassPriceTier).filter(models.PassPriceTier.pass_id == pass_id).delete()
    for tier in payload.price_tiers:
        db.add(models.PassPriceTier(pass_id=pass_id, duration_days=tier.duration_days, price=tier.price))

    _sync_primary_tier(pass_row, payload.price_tiers)
    db.commit()

    return schemas.AdminPassResponse(id=pass_row.id, message=f"{pass_row.name}(으)로 저장했어요")


@router.patch("/passes/{pass_id}/status", response_model=schemas.AdminPassResponse)
def toggle_pass_status(pass_id: int, payload: schemas.PassStatusRequest, db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)

    pass_row.sale_status = payload.sale_status
    db.commit()

    label = "판매중" if payload.sale_status == "on_sale" else "판매 중단"
    return schemas.AdminPassResponse(id=pass_row.id, message=f"{pass_row.name}을(를) {label}으로 변경했어요")
