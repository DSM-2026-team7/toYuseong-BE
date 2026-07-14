from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from web import schemas
from web.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin-passes"], dependencies=[Depends(require_admin)])

NOT_FOUND = {"error": "pass_not_found", "message": "패스를 찾을 수 없어요"}


def _validate_tiers(tiers: list[schemas.PassPriceTierItem]) -> None:
    if not tiers:
        raise HTTPException(
            status_code=400,
            detail={"error": "pass_price_required", "message": "패스 기간과 가격을 입력해 주세요"},
        )


def _resolved_tiers(
    payload: schemas.AdminPassCreateRequest | schemas.AdminPassUpdateRequest,
    existing: list[schemas.PassPriceTierItem] | None = None,
) -> list[schemas.PassPriceTierItem]:
    if payload.price_tiers:
        tiers = payload.price_tiers
    elif payload.duration_days is not None and payload.price is not None:
        tiers = [
            schemas.PassPriceTierItem(
                duration_days=payload.duration_days,
                price=payload.price,
            )
        ]
    elif payload.duration_days is not None or payload.price is not None:
        raise HTTPException(
            status_code=400,
            detail={"error": "pass_price_required", "message": "기간과 가격을 함께 입력해 주세요"},
        )
    elif existing is not None:
        tiers = existing
    else:
        tiers = []
    _validate_tiers(tiers)
    return tiers
    durations = [tier.duration_days for tier in tiers]
    if len(durations) != len(set(durations)):
        raise HTTPException(
            status_code=400,
            detail={"error": "duplicate_pass_duration", "message": "동일한 기간 옵션을 중복 등록할 수 없어요"},
        )


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
    passes = (
        db.query(models.Pass)
        .filter(models.Pass.sale_status != "deleted")
        .order_by(models.Pass.id)
        .all()
    )
    items = [
        schemas.AdminPassListItem(
            id=p.id,
            name=p.name,
            scope=p.scope,
            scope_category=p.scope_category,
            discount_rate=p.discount_rate,
            duration_days=p.duration_days,
            price=p.price,
            max_discount_amount=p.max_discount_amount,
            price_tiers=_get_price_tiers(db, p.id),
            sale_status=p.sale_status,
        )
        for p in passes
    ]
    return schemas.AdminPassListResponse(passes=items)


@router.get("/passes/{pass_id}", response_model=schemas.AdminPassDetailResponse)
def get_pass(pass_id: int, db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None or pass_row.sale_status == "deleted":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return schemas.AdminPassDetailResponse(
        id=pass_row.id,
        name=pass_row.name,
        scope=pass_row.scope,
        scope_category=pass_row.scope_category,
        scope_store_id=pass_row.scope_store_id,
        discount_rate=pass_row.discount_rate,
        target_desc=pass_row.target_desc,
        max_discount_amount=pass_row.max_discount_amount,
        price_tiers=_get_price_tiers(db, pass_row.id),
        sale_status=pass_row.sale_status,
    )


@router.post("/passes", response_model=schemas.AdminPassResponse, status_code=201)
def create_pass(payload: schemas.AdminPassCreateRequest, db: Session = Depends(get_db)):
    tiers = _resolved_tiers(payload)
    first_tier = tiers[0]
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
        max_discount_amount=payload.max_discount_amount,
    )
    db.add(pass_row)
    db.flush()

    for tier in tiers:
        db.add(models.PassPriceTier(pass_id=pass_row.id, duration_days=tier.duration_days, price=tier.price))
    db.commit()

    return schemas.AdminPassResponse(id=pass_row.id, message=f"{pass_row.name}을(를) 등록했어요")


@router.put("/passes/{pass_id}", response_model=schemas.AdminPassResponse)
def update_pass(pass_id: int, payload: schemas.AdminPassUpdateRequest, db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None or pass_row.sale_status == "deleted":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    tiers = _resolved_tiers(payload, _get_price_tiers(db, pass_id))
    fields = payload.model_fields_set
    required_updates = {
        "name": payload.name,
        "scope": payload.scope,
        "discount_rate": payload.discount_rate,
        "target_desc": payload.target_desc,
        "sale_status": payload.sale_status,
    }
    if any(key in fields and value is None for key, value in required_updates.items()):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_pass", "message": "패스 필수 정보는 비울 수 없어요"},
        )
    if "name" in fields:
        pass_row.name = payload.name
    if "scope" in fields:
        pass_row.scope = payload.scope
    if "scope_category" in fields:
        pass_row.scope_category = payload.scope_category
    if "scope_store_id" in fields:
        pass_row.scope_store_id = payload.scope_store_id
    if "discount_rate" in fields:
        pass_row.discount_rate = payload.discount_rate
    if "target_desc" in fields:
        pass_row.target_desc = payload.target_desc
    if "sale_status" in fields:
        pass_row.sale_status = payload.sale_status
    if "max_discount_amount" in fields:
        pass_row.max_discount_amount = payload.max_discount_amount

    # 기존 price tiers 삭제 후 재생성
    db.query(models.PassPriceTier).filter(models.PassPriceTier.pass_id == pass_id).delete()
    for tier in tiers:
        db.add(models.PassPriceTier(pass_id=pass_id, duration_days=tier.duration_days, price=tier.price))

    _sync_primary_tier(pass_row, tiers)
    db.commit()

    return schemas.AdminPassResponse(id=pass_row.id, message=f"{pass_row.name}(으)로 저장했어요")


@router.patch("/passes/{pass_id}/status", response_model=schemas.AdminPassResponse)
def toggle_pass_status(pass_id: int, payload: schemas.PassStatusRequest, db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None or pass_row.sale_status == "deleted":
        raise HTTPException(status_code=404, detail=NOT_FOUND)

    pass_row.sale_status = payload.sale_status
    db.commit()

    label = "판매중" if payload.sale_status == "on_sale" else "판매 중단"
    return schemas.AdminPassResponse(id=pass_row.id, message=f"{pass_row.name}을(를) {label}으로 변경했어요")


@router.delete("/passes/{pass_id}", response_model=schemas.AdminPassResponse)
def delete_pass(pass_id: int, db: Session = Depends(get_db)):
    pass_row = db.get(models.Pass, pass_id)
    if pass_row is None or pass_row.sale_status == "deleted":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    pass_row.sale_status = "deleted"
    db.commit()
    return schemas.AdminPassResponse(id=pass_row.id, message=f"{pass_row.name}을(를) 삭제했어요")
