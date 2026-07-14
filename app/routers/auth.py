from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

USER_NOT_FOUND_ERROR = {"error": "user_not_found", "message": "계정을 찾을 수 없어요"}


def _role_mismatch_error(role: str) -> dict:
    label = "사장님" if role == "owner" else "사용자"
    return {"error": "role_mismatch", "message": f"{label} 계정이 아니에요"}


def _owner_store(db: Session, owner_id: int) -> models.Store | None:
    return db.query(models.Store).filter(models.Store.owner_id == owner_id).first()


@router.get("/accounts", response_model=schemas.AuthAccountsResponse)
def list_accounts(db: Session = Depends(get_db)):
    """데모 로그인 화면에서 고를 수 있는 계정 목록.

    비밀번호가 없으므로 로그인 전에 '누구로 로그인할지' 프론트가 보여줄 목록이 필요해서 추가했다.
    명세(API.md)에는 없는 데모 전용 엔드포인트다.
    """
    accounts: list[schemas.AuthAccountItem] = []

    customers = (
        db.query(models.User).filter(models.User.role == "customer").order_by(models.User.id).all()
    )
    for user in customers:
        accounts.append(schemas.AuthAccountItem(role="customer", user_id=user.id, nickname=user.nickname))

    owners = db.query(models.User).filter(models.User.role == "owner").order_by(models.User.id).all()
    for user in owners:
        store = _owner_store(db, user.id)
        accounts.append(
            schemas.AuthAccountItem(
                role="owner",
                user_id=user.id,
                nickname=user.nickname,
                store_id=store.id if store else None,
                store_name=store.name if store else None,
            )
        )

    return schemas.AuthAccountsResponse(accounts=accounts)


@router.post("/login", response_model=schemas.AuthLoginResponse)
def login(body: schemas.AuthLoginRequest, db: Session = Depends(get_db)):
    """비밀번호 없는 데모 로그인. role(customer/owner)을 골라 그 역할로 로그인한다.

    - role=customer: 이후 요청에 `X-User-Id: <user_id>` 헤더를 실어 보내면 된다.
    - role=owner: 응답의 `token`을 `Authorization: Bearer <token>`으로 실어 보내면
      기존 사장님 전용 API(`/admin/*`)를 그대로 쓸 수 있다 (`require_owner_id`가 받는 형식).
    """
    user = db.get(models.User, body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND_ERROR)
    if user.role != body.role:
        raise HTTPException(status_code=403, detail=_role_mismatch_error(body.role))

    if body.role == "owner":
        store = _owner_store(db, user.id)
        return schemas.AuthLoginResponse(
            role="owner",
            user_id=user.id,
            nickname=user.nickname,
            store_id=store.id if store else None,
            store_name=store.name if store else None,
            token=str(user.id),
        )

    return schemas.AuthLoginResponse(
        role="customer",
        user_id=user.id,
        nickname=user.nickname,
        region=user.region,
    )
