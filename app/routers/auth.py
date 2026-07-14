from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.google_oauth import verify_google_credential
from app.utils import create_user_token, owner_verification_status, require_user_id, user_roles

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
    role_enabled = user.owner_enabled if body.role == "owner" else user.customer_enabled
    if not role_enabled:
        raise HTTPException(status_code=403, detail=_role_mismatch_error(body.role))

    user.role = body.role
    db.commit()

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


@router.post("/google", response_model=schemas.GoogleLoginResponse)
def google_login(body: schemas.GoogleLoginRequest, db: Session = Depends(get_db)):
    claims = verify_google_credential(body.credential)
    google_sub = str(claims["sub"])
    user = db.query(models.User).filter(models.User.google_sub == google_sub).first()
    is_new = user is None

    if user is None:
        nickname = str(claims.get("name") or claims.get("email") or "사용자")
        user = models.User(
            google_sub=google_sub,
            email=claims.get("email"),
            profile_image_url=claims.get("picture"),
            nickname=nickname,
            region="",
            role="pending",
            customer_enabled=False,
            owner_enabled=False,
            onboarding_completed=False,
            location_permission="unknown",
        )
        db.add(user)
        db.flush()
    else:
        user.email = claims.get("email") or user.email
        user.profile_image_url = claims.get("picture") or user.profile_image_url

    db.commit()
    return schemas.GoogleLoginResponse(
        user_id=user.id,
        token=create_user_token(user.id),
        role=user.role,
        roles=user_roles(user),
        is_new=is_new,
        requires_role_selection=not user.onboarding_completed,
        nickname=user.nickname,
        email=user.email,
        profile_image_url=user.profile_image_url,
        store_verification=owner_verification_status(db, user.id),
    )


@router.post("/role", response_model=schemas.RoleSwitchResponse)
def select_role(
    body: schemas.RoleSelectRequest,
    x_user_id: int = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    user = db.get(models.User, x_user_id)
    if body.role == "customer":
        user.customer_enabled = True
    else:
        user.owner_enabled = True
    user.role = body.role
    user.onboarding_completed = True
    if body.region is not None:
        user.region = body.region
    db.commit()

    verification = owner_verification_status(db, user.id)
    store_required = body.role == "owner" and verification != "approved"
    return schemas.RoleSwitchResponse(
        role=body.role,
        roles=user_roles(user),
        store_verification_required=store_required,
        store_verification=verification,
    )


@router.post("/logout", response_model=schemas.LogoutResponse)
def logout():
    return schemas.LogoutResponse(message="로그아웃됐어요")
