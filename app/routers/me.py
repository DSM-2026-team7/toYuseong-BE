import base64
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import require_user_id

router = APIRouter(tags=["me"])

PAGE_SIZE = 20

FILTER_TYPES = {
    "coupon": ["coupon_use", "coupon_claim", "coupon_expire"],
    "stamp": ["stamp_earn", "reward_issue"],
    "pass": ["pass_use", "pass_purchase"],
}


def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.b64decode(padded.encode("utf-8")))
        return int(data.get("offset", 0))
    except Exception:
        return 0


def _encode_cursor(offset: int) -> str:
    return base64.b64encode(json.dumps({"offset": offset}).encode("utf-8")).decode("utf-8")


@router.get("/me", response_model=schemas.MeResponse)
def get_me(x_user_id: int = Depends(require_user_id), db: Session = Depends(get_db)):
    # require_user_id가 이미 존재하는 유저인지 검증했으므로 여기서는 바로 조회한다.
    user = db.get(models.User, x_user_id)
    unread_count = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == x_user_id, models.Notification.read.is_(False))
        .count()
    )
    return schemas.MeResponse(
        id=user.id,
        nickname=user.nickname,
        region=user.region,
        role=user.role,
        unread_notifications=unread_count,
    )


@router.get("/me/notifications", response_model=schemas.NotificationsResponse)
def list_notifications(x_user_id: int = Depends(require_user_id), db: Session = Depends(get_db)):
    """알림 아이콘을 눌렀을 때 보여줄 목업 API. 명세(API.md)에는 없는 데모용 부가 기능이다.

    조회 시점의 읽음 여부를 응답에 담아 반환한 뒤, 그 알림들은 읽음 처리한다
    (벨 아이콘을 누르면 뱃지 숫자가 사라지는 흔한 UX를 흉내낸다).
    """
    notifications = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == x_user_id)
        .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
        .all()
    )

    items = [
        schemas.NotificationItem(
            id=n.id, title=n.title, body=n.body, read=n.read, created_at=n.created_at
        )
        for n in notifications
    ]

    unread = [n for n in notifications if not n.read]
    for n in unread:
        n.read = True
    if unread:
        db.commit()

    return schemas.NotificationsResponse(notifications=items)


@router.get("/me/transactions", response_model=schemas.TransactionsResponse)
def list_transactions(
    filter: str = Query(default="all"),
    cursor: Optional[str] = Query(default=None),
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    query = db.query(models.Transaction).filter(models.Transaction.user_id == x_user_id)
    if filter != "all":
        query = query.filter(models.Transaction.type.in_(FILTER_TYPES.get(filter, [])))

    query = query.order_by(models.Transaction.created_at.desc(), models.Transaction.id.desc())

    offset = _decode_cursor(cursor)
    rows = query.offset(offset).limit(PAGE_SIZE + 1).all()

    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    items = [
        schemas.TransactionItem(
            id=row.id,
            type=row.type,
            store_name=row.store_name,
            amount=row.amount,
            memo=row.memo,
            created_at=row.created_at,
        )
        for row in rows
    ]

    next_cursor = _encode_cursor(offset + PAGE_SIZE) if has_more else None

    return schemas.TransactionsResponse(transactions=items, next_cursor=next_cursor)
