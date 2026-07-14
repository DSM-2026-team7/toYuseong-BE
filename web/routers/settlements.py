from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.utils import utc_now
from web import schemas
from web.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin-settlements"], dependencies=[Depends(require_admin)])


def _mask_name(name: str) -> str:
    """홍길동 → 홍** 식으로 마스킹."""
    if len(name) <= 1:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 1)


def _get_store_subsidy(db: Session, store: models.Store, year: int, month: int) -> tuple[int, int]:
    """특정 매장·기간의 패스 사용 건수와 보전금액(할인액 절댓값 합)을 반환한다."""
    result = (
        db.query(
            func.count(models.Transaction.id),
            func.coalesce(func.sum(func.abs(models.Transaction.amount)), 0),
        )
        .filter(
            models.Transaction.type == "pass_use",
            models.Transaction.store_name == store.name,
            extract("year", models.Transaction.created_at) == year,
            extract("month", models.Transaction.created_at) == month,
        )
        .one()
    )
    return int(result[0]), int(result[1])


def _get_settlement_status(db: Session, store_id: int, year: int, month: int) -> Optional[models.Settlement]:
    return (
        db.query(models.Settlement)
        .filter(
            models.Settlement.store_id == store_id,
            models.Settlement.year == year,
            models.Settlement.month == month,
        )
        .first()
    )


@router.get("/settlements", response_model=schemas.SettlementListResponse)
def list_settlements(
    year: int = Query(default=None),
    month: int = Query(default=None),
    store_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """정산 목록: 기간별 통계 3개 + 가맹점별 보전금액·정산상태."""
    now = utc_now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    stores_query = db.query(models.Store)
    if store_id is not None:
        stores_query = stores_query.filter(models.Store.id == store_id)
    stores = stores_query.order_by(models.Store.id).all()

    items: list[schemas.SettlementStoreItem] = []
    total_subsidy = 0
    pending_amount = 0
    completed_amount = 0

    for store in stores:
        count, amount = _get_store_subsidy(db, store, year, month)
        if count == 0:
            continue

        settlement = _get_settlement_status(db, store.id, year, month)
        status = settlement.status if settlement else "pending"

        items.append(
            schemas.SettlementStoreItem(
                store_id=store.id,
                store_name=store.name,
                transaction_count=count,
                subsidy_amount=amount,
                status=status,
            )
        )
        total_subsidy += amount
        if status == "completed":
            completed_amount += amount
        else:
            pending_amount += amount

    return schemas.SettlementListResponse(
        stats=schemas.SettlementStats(
            total_subsidy=total_subsidy,
            pending_amount=pending_amount,
            completed_amount=completed_amount,
        ),
        stores=items,
        year=year,
        month=month,
    )


@router.get("/settlements/{target_store_id}", response_model=schemas.SettlementDetailResponse)
def get_settlement_detail(
    target_store_id: int,
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db),
):
    """가맹점 상세 정산: 개별 패스 사용 거래 목록."""
    store = db.get(models.Store, target_store_id)
    if store is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "store_not_found", "message": "매장을 찾을 수 없어요"},
        )

    now = utc_now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    txns = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.type == "pass_use",
            models.Transaction.store_name == store.name,
            extract("year", models.Transaction.created_at) == year,
            extract("month", models.Transaction.created_at) == month,
        )
        .order_by(models.Transaction.created_at.desc())
        .all()
    )

    items: list[schemas.SettlementTransactionItem] = []
    total_subsidy = 0
    for txn in txns:
        discount_amount = abs(txn.amount) if txn.amount else 0
        total_subsidy += discount_amount

        # 사용자 이름 마스킹
        user = db.get(models.User, txn.user_id)
        user_name = _mask_name(user.nickname) if user else "알 수 없음"

        # 할인율 — 패스에서 조회 (해커톤 단순화: 해당 매장에 적용 가능한 패스 중 첫 번째)
        discount_rate = 10  # 기본값
        user_passes = (
            db.query(models.UserPass)
            .filter(models.UserPass.user_id == txn.user_id)
            .all()
        )
        for up in user_passes:
            p = db.get(models.Pass, up.pass_id)
            if p:
                discount_rate = p.discount_rate
                break

        payment_amount = round(discount_amount * 100 / discount_rate) if discount_rate > 0 else 0

        items.append(
            schemas.SettlementTransactionItem(
                timestamp=txn.created_at,
                user_name=user_name,
                payment_amount=payment_amount,
                discount_rate=discount_rate,
                discount_amount=discount_amount,
                note=txn.memo,
            )
        )

    return schemas.SettlementDetailResponse(
        store_id=store.id,
        store_name=store.name,
        year=year,
        month=month,
        transaction_count=len(items),
        total_subsidy=total_subsidy,
        transactions=items,
    )


@router.post("/settlements/{target_store_id}/process", response_model=schemas.SettlementProcessResponse)
def process_settlement(
    target_store_id: int,
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db),
):
    """가맹점 정산 처리 (보전금 지급 완료 처리)."""
    store = db.get(models.Store, target_store_id)
    if store is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "store_not_found", "message": "매장을 찾을 수 없어요"},
        )

    now = utc_now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    existing = _get_settlement_status(db, store.id, year, month)
    if existing and existing.status == "completed":
        raise HTTPException(
            status_code=409,
            detail={"error": "already_settled", "message": "이미 정산이 완료된 건이에요"},
        )

    _, amount = _get_store_subsidy(db, store, year, month)

    if existing:
        existing.status = "completed"
        existing.amount = amount
        existing.processed_at = now
    else:
        db.add(
            models.Settlement(
                store_id=store.id,
                year=year,
                month=month,
                amount=amount,
                status="completed",
                processed_at=now,
            )
        )
    db.commit()

    return schemas.SettlementProcessResponse(
        store_id=store.id,
        store_name=store.name,
        amount=amount,
        status="completed",
        message=f"{store.name}의 미정산 분에 {amount:,}원 지급",
    )
