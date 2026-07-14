from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from web import schemas
from web.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin-dashboard"], dependencies=[Depends(require_admin)])


@router.get("/dashboard", response_model=schemas.DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)):
    """대시보드: 통계 카드 4개 + 최근 활동 + 가맹점 심사 대기 건수."""

    # ── 통계 ──
    total_issued = db.query(func.count(models.UserCoupon.id)).scalar() or 0
    total_used = (
        db.query(func.count(models.UserCoupon.id))
        .filter(models.UserCoupon.status == "used")
        .scalar()
        or 0
    )
    registered_stores = db.query(func.count(models.Store.id)).scalar() or 0

    # 보전 예상 금액 = 쿠폰/패스 사용 할인액의 절댓값 합
    subsidy = (
        db.query(func.sum(func.abs(models.Transaction.amount)))
        .filter(models.Transaction.type.in_(["coupon_use", "pass_use"]))
        .scalar()
        or 0
    )

    # ── 최근 활동 ──
    recent_txns = (
        db.query(models.Transaction)
        .order_by(models.Transaction.created_at.desc())
        .limit(10)
        .all()
    )

    type_map = {
        "stamp_earn": "스탬프",
        "reward_issue": "쿠폰",
        "coupon_claim": "쿠폰",
        "coupon_use": "쿠폰",
        "pass_purchase": "패스",
        "pass_use": "패스",
    }
    content_map = {
        "stamp_earn": "스탬프 적립",
        "reward_issue": "리워드 쿠폰 발급",
        "coupon_claim": "쿠폰 수령",
        "coupon_use": "쿠폰 사용",
        "pass_purchase": "패스 구매",
        "pass_use": "패스 사용 할인",
    }

    activities: list[schemas.RecentActivityItem] = []
    for txn in recent_txns:
        activities.append(
            schemas.RecentActivityItem(
                timestamp=txn.created_at,
                type=txn.type,
                type_label=type_map.get(txn.type, "기타"),
                store_name=txn.store_name,
                content=txn.memo or content_map.get(txn.type, txn.type),
                status="완료",
                note=f"{txn.amount:,}원" if txn.amount else None,
            )
        )

    # 최근 가맹점 심사 이벤트도 활동에 포함
    recent_apps = (
        db.query(models.StoreApplication)
        .filter(models.StoreApplication.reviewed_at.isnot(None))
        .order_by(models.StoreApplication.reviewed_at.desc())
        .limit(5)
        .all()
    )
    for app_row in recent_apps:
        label = "승인" if app_row.status == "approved" else "반려"
        activities.append(
            schemas.RecentActivityItem(
                timestamp=app_row.reviewed_at,
                type="application_review",
                type_label="심사",
                store_name=app_row.name,
                content=f"신규 가맹점 {label}",
                status=label,
                note=None,
            )
        )

    # 시간순 정렬
    activities.sort(key=lambda a: a.timestamp, reverse=True)
    activities = activities[:10]

    # ── 가맹점 심사 건수 ──
    pending = (
        db.query(func.count(models.StoreApplication.id))
        .filter(models.StoreApplication.status == "pending")
        .scalar()
        or 0
    )
    reviewed = (
        db.query(func.count(models.StoreApplication.id))
        .filter(models.StoreApplication.status != "pending")
        .scalar()
        or 0
    )

    return schemas.DashboardResponse(
        stats=schemas.DashboardStats(
            total_coupons_issued=total_issued,
            total_coupons_used=total_used,
            registered_stores=registered_stores,
            estimated_subsidy=subsidy,
        ),
        recent_activities=activities,
        pending_applications=pending,
        total_applications_reviewed=reviewed,
    )
