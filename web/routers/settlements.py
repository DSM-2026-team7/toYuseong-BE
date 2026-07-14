from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.utils import seoul_month_bounds_for, utc_now
from web import schemas
from web.auth import require_admin

router = APIRouter(
    prefix="/admin",
    tags=["admin-settlements"],
    dependencies=[Depends(require_admin)],
)


def _mask_name(name: str) -> str:
    if len(name) <= 1:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 1)


def _period(year: Optional[int], month: Optional[int]) -> tuple[int, int, datetime, datetime]:
    seoul_now = datetime.now(timezone(timedelta(hours=9)))
    resolved_year = year if year is not None else seoul_now.year
    resolved_month = month if month is not None else seoul_now.month
    try:
        start, end = seoul_month_bounds_for(resolved_year, resolved_month)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_settlement_month", "message": "정산 대상 월을 확인해 주세요"},
        ) from exc
    return resolved_year, resolved_month, start, end


def _store_transaction_condition(store: models.Store):
    # 새 거래는 store_id로, 마이그레이션 전 거래는 기존 매장명으로 연결한다.
    return or_(
        models.Transaction.store_id == store.id,
        and_(
            models.Transaction.store_id.is_(None),
            models.Transaction.store_name == store.name,
        ),
    )


def _get_store_subsidy(
    db: Session,
    store: models.Store,
    start: datetime,
    end: datetime,
    *,
    locked_at: Optional[datetime] = None,
) -> tuple[int, int]:
    query = db.query(
        func.count(models.Transaction.id),
        func.coalesce(func.sum(func.abs(models.Transaction.amount)), 0),
    ).filter(
        models.Transaction.type == "pass_use",
        _store_transaction_condition(store),
        models.Transaction.created_at >= start,
        models.Transaction.created_at < end,
    )
    if locked_at is not None:
        query = query.filter(models.Transaction.created_at <= locked_at)
    count, amount = query.one()
    return int(count), int(amount)


def _get_settlement_status(
    db: Session,
    store_id: int,
    year: int,
    month: int,
) -> Optional[models.Settlement]:
    return (
        db.query(models.Settlement)
        .filter(
            models.Settlement.store_id == store_id,
            models.Settlement.year == year,
            models.Settlement.month == month,
        )
        .first()
    )


def _settlement_values(
    db: Session,
    store: models.Store,
    year: int,
    month: int,
    start: datetime,
    end: datetime,
) -> tuple[int, int, str, Optional[models.Settlement]]:
    settlement = _get_settlement_status(db, store.id, year, month)
    if settlement is not None and settlement.status == "completed":
        return settlement.transaction_count, settlement.amount, "completed", settlement
    count, amount = _get_store_subsidy(db, store, start, end)
    return count, amount, "pending", settlement


@router.get("/settlements", response_model=schemas.SettlementListResponse)
def list_settlements(
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
    store_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    year, month, start, end = _period(year, month)
    stores_query = db.query(models.Store).filter(models.Store.verification_status == "approved")
    if store_id is not None:
        stores_query = stores_query.filter(models.Store.id == store_id)

    items: list[schemas.SettlementStoreItem] = []
    total_subsidy = pending_amount = completed_amount = 0
    for store in stores_query.order_by(models.Store.id).all():
        count, amount, status, settlement = _settlement_values(
            db, store, year, month, start, end
        )
        if count == 0 and settlement is None:
            continue
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
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    store = db.get(models.Store, target_store_id)
    if store is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "store_not_found", "message": "매장을 찾을 수 없어요"},
        )

    year, month, start, end = _period(year, month)
    settlement = _get_settlement_status(db, store.id, year, month)
    locked_at = (
        settlement.processed_at
        if settlement is not None and settlement.status == "completed"
        else None
    )
    query = db.query(models.Transaction).filter(
        models.Transaction.type == "pass_use",
        _store_transaction_condition(store),
        models.Transaction.created_at >= start,
        models.Transaction.created_at < end,
    )
    if locked_at is not None:
        query = query.filter(models.Transaction.created_at <= locked_at)
    transactions = query.order_by(models.Transaction.created_at.desc()).all()

    items: list[schemas.SettlementTransactionItem] = []
    total_subsidy = 0
    for transaction in transactions:
        discount_amount = abs(transaction.amount) if transaction.amount else 0
        total_subsidy += discount_amount
        user = db.get(models.User, transaction.user_id)
        user_name = _mask_name(user.nickname) if user else "알 수 없음"

        discount_rate = transaction.discount_rate
        if discount_rate is None:
            # 마이그레이션 전 거래만 기존 데이터로 추정한다.
            user_pass = (
                db.query(models.UserPass)
                .filter(models.UserPass.user_id == transaction.user_id)
                .order_by(models.UserPass.purchased_at.desc())
                .first()
            )
            pass_row = db.get(models.Pass, user_pass.pass_id) if user_pass else None
            discount_rate = (
                user_pass.discount_rate_snapshot
                if user_pass and user_pass.discount_rate_snapshot is not None
                else pass_row.discount_rate if pass_row else 10
            )
        payment_amount = (
            round(discount_amount * 100 / discount_rate) if discount_rate > 0 else 0
        )
        items.append(
            schemas.SettlementTransactionItem(
                timestamp=transaction.created_at,
                user_name=user_name,
                payment_amount=payment_amount,
                discount_rate=discount_rate,
                discount_amount=discount_amount,
                note=transaction.memo,
            )
        )

    if settlement is not None and settlement.status == "completed":
        total_subsidy = settlement.amount

    return schemas.SettlementDetailResponse(
        store_id=store.id,
        store_name=store.name,
        year=year,
        month=month,
        transaction_count=(
            settlement.transaction_count
            if settlement is not None and settlement.status == "completed"
            else len(items)
        ),
        total_subsidy=total_subsidy,
        transactions=items,
        status=settlement.status if settlement else "pending",
        processed_at=settlement.processed_at if settlement else None,
    )


def _complete_settlement(
    db: Session,
    store: models.Store,
    year: int,
    month: int,
    start: datetime,
    end: datetime,
    now: datetime,
) -> schemas.SettlementProcessResponse:
    existing = _get_settlement_status(db, store.id, year, month)
    if existing is not None and existing.status == "completed":
        raise HTTPException(
            status_code=409,
            detail={"error": "already_settled", "message": "이미 정산이 완료된 건이에요"},
        )
    count, amount = _get_store_subsidy(db, store, start, end, locked_at=now)
    if count == 0:
        raise HTTPException(
            status_code=400,
            detail={"error": "no_settlement_target", "message": "정산할 패스 사용 내역이 없어요"},
        )

    settlement = existing or models.Settlement(
        store_id=store.id,
        year=year,
        month=month,
    )
    settlement.amount = amount
    settlement.transaction_count = count
    settlement.status = "completed"
    settlement.processed_at = now
    db.add(settlement)
    return schemas.SettlementProcessResponse(
        store_id=store.id,
        store_name=store.name,
        amount=amount,
        status="completed",
        transaction_count=count,
        processed_at=now,
        message=f"{store.name}의 {year}년 {month}월 정산 {amount:,}원을 지급 완료 처리했어요",
    )


@router.post(
    "/settlements/process-all",
    response_model=schemas.SettlementBatchProcessResponse,
)
def process_all_settlements(
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    year, month, start, end = _period(year, month)
    now = utc_now()
    results: list[schemas.SettlementProcessResponse] = []
    for store in (
        db.query(models.Store)
        .filter(models.Store.verification_status == "approved")
        .order_by(models.Store.id)
        .all()
    ):
        existing = _get_settlement_status(db, store.id, year, month)
        if existing is not None and existing.status == "completed":
            continue
        count, _ = _get_store_subsidy(db, store, start, end, locked_at=now)
        if count == 0:
            continue
        results.append(_complete_settlement(db, store, year, month, start, end, now))
    db.commit()
    total_amount = sum(result.amount for result in results)
    return schemas.SettlementBatchProcessResponse(
        year=year,
        month=month,
        processed_store_count=len(results),
        total_amount=total_amount,
        stores=results,
        message=f"{len(results)}개 매장, 총 {total_amount:,}원을 지급 완료 처리했어요",
    )


@router.post(
    "/settlements/{target_store_id}/process",
    response_model=schemas.SettlementProcessResponse,
)
def process_settlement(
    target_store_id: int,
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    store = db.get(models.Store, target_store_id)
    if store is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "store_not_found", "message": "매장을 찾을 수 없어요"},
        )
    year, month, start, end = _period(year, month)
    result = _complete_settlement(
        db,
        store,
        year,
        month,
        start,
        end,
        utc_now(),
    )
    db.commit()
    return result
