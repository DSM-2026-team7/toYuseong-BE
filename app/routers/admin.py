import re
from io import BytesIO
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import PAYMENT_QR_TTL_MINUTES
from app.database import get_db
from app.utils import iso_z, require_owner_id, seoul_month_bounds, utc_now

router = APIRouter(prefix="/admin", tags=["admin"])


def error(code: int, name: str, message: str):
    raise HTTPException(code, detail={"error": name, "message": message})


def raw_owner_store(db: Session, owner_id: int) -> models.Store | None:
    return db.query(models.Store).filter(models.Store.owner_id == owner_id).first()


def latest_application(db: Session, owner_id: int) -> models.StoreApplication | None:
    return (
        db.query(models.StoreApplication)
        .filter(models.StoreApplication.owner_id == owner_id)
        .order_by(models.StoreApplication.applied_at.desc(), models.StoreApplication.id.desc())
        .first()
    )


def owner_store(db: Session, owner_id: int) -> models.Store:
    store = raw_owner_store(db, owner_id)
    if store is None:
        application = latest_application(db, owner_id)
        if application is not None and application.status == "pending":
            error(403, "store_verification_pending", "매장 인증 심사 중이에요.")
        error(404, "shop_not_found", "등록된 매장이 없습니다.")
    if store.verification_status != "approved":
        error(403, "store_verification_pending", "매장 재인증 심사 중이에요.")
    return store


def derive_region(address: str, supplied_region: str | None = None) -> str:
    if supplied_region and supplied_region.strip():
        return supplied_region.strip()
    match = re.search(r"(?:유성구\s+)?([가-힣0-9]+동)", address)
    if match:
        return f"유성구 {match.group(1)}"
    error(400, "region_not_resolved", "주소에서 지역(동)을 확인할 수 없어요.")


def verification_response(db: Session, owner_id: int) -> schemas.StoreVerificationResponse:
    store = raw_owner_store(db, owner_id)
    application = latest_application(db, owner_id)
    if application is not None and application.status == "pending":
        return schemas.StoreVerificationResponse(
            status="pending",
            application_id=application.id,
            store_id=store.id if store else None,
            message="매장 인증 심사 중이에요",
        )
    if store is not None and store.verification_status == "approved":
        return schemas.StoreVerificationResponse(
            status="approved",
            application_id=application.id if application else None,
            store_id=store.id,
            message="매장 인증이 완료됐어요",
        )
    return schemas.StoreVerificationResponse(
        status="none",
        application_id=application.id if application else None,
        store_id=store.id if store else None,
        reject_reason=application.reject_reason if application and application.status == "rejected" else None,
        message="매장 인증이 필요해요",
    )


@router.post("/register", status_code=201, response_model=schemas.StoreVerificationResponse)
def register_shop(body: schemas.AdminRegisterRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    if not body.name.strip() or not body.register_num.strip() or not body.address.strip() or not body.phone_no.strip():
        error(400, "invalid_request", "매장 인증 필수 정보를 모두 입력해 주세요.")
    if raw_owner_store(db, owner_id) is not None:
        error(409, "already_registered", "이미 등록된 사업자입니다.")
    existing_application = latest_application(db, owner_id)
    if existing_application is not None and existing_application.status == "pending":
        error(409, "verification_already_pending", "이미 매장 인증 심사 중이에요.")
    if db.query(models.Store).filter(models.Store.register_num == body.register_num).first():
        error(409, "already_registered", "이미 등록된 사업자입니다.")
    duplicate_pending = (
        db.query(models.StoreApplication)
        .filter(
            models.StoreApplication.business_number == body.register_num,
            models.StoreApplication.status == "pending",
        )
        .first()
    )
    if duplicate_pending is not None:
        error(409, "already_registered", "이미 심사 중인 사업자 번호예요.")

    user = db.get(models.User, owner_id)
    application = models.StoreApplication(
        owner_id=owner_id,
        name=body.name.strip(),
        category=body.category,
        region=derive_region(body.address, body.region),
        business_number=body.register_num.strip(),
        business_hours=body.business_hours or "",
        phone=body.phone_no.strip(),
        applicant_name=user.nickname,
        address=body.address.strip(),
        latitude=body.latitude,
        longitude=body.longitude,
        application_type="initial",
        status="pending",
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return verification_response(db, owner_id)


@router.get("/verification", response_model=schemas.StoreVerificationResponse)
def get_verification(owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    return verification_response(db, owner_id)


@router.get("/shop", response_model=schemas.AdminStoreResponse)
def get_shop(owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    return owner_store(db, owner_id)


@router.patch("/shop", status_code=202, response_model=schemas.StoreVerificationResponse)
def update_shop(
    body: schemas.AdminStoreUpdateRequest,
    owner_id: int = Depends(require_owner_id),
    db: Session = Depends(get_db),
):
    store = owner_store(db, owner_id)
    if latest_application(db, owner_id) is not None and latest_application(db, owner_id).status == "pending":
        error(409, "verification_already_pending", "이미 매장 재인증 심사 중이에요.")

    values = body.model_dump(exclude_none=True)
    if not values:
        error(400, "invalid_request", "수정할 매장 정보를 입력해 주세요.")
    for key in ("name", "register_num", "address", "phone_no"):
        if key in values and not values[key].strip():
            error(400, "invalid_request", "매장 정보는 빈 값으로 수정할 수 없습니다.")
    address = values.get("address", store.address or "")
    supplied_region = values.get("region")
    if supplied_region is None and "address" not in values:
        supplied_region = store.region
    region = derive_region(address, supplied_region)
    register_num = values.get("register_num", store.register_num)
    if register_num != store.register_num:
        duplicate = db.query(models.Store).filter(models.Store.register_num == register_num).first()
        if duplicate is not None:
            error(409, "already_registered", "이미 등록된 사업자입니다.")

    user = db.get(models.User, owner_id)
    application = models.StoreApplication(
        owner_id=owner_id,
        store_id=store.id,
        name=values.get("name", store.name),
        category=values.get("category", store.category),
        region=region,
        business_number=register_num or "",
        business_hours=values.get("business_hours", store.business_hours),
        phone=values.get("phone_no", store.phone_no or ""),
        applicant_name=user.nickname,
        address=address,
        latitude=values.get("latitude", store.latitude),
        longitude=values.get("longitude", store.longitude),
        application_type="reverification",
        status="pending",
    )
    store.verification_status = "pending"
    db.add(application)
    db.commit()
    return verification_response(db, owner_id)


@router.get("/owner/dashboard", response_model=schemas.OwnerDashboardResponse)
def get_owner_dashboard(
    owner_id: int = Depends(require_owner_id),
    db: Session = Depends(get_db),
):
    store = owner_store(db, owner_id)
    month_start, next_month = seoul_month_bounds()
    settlement_expected = int(
        db.query(func.coalesce(func.sum(func.abs(models.Transaction.amount)), 0))
        .filter(
            models.Transaction.type == "pass_use",
            or_(
                models.Transaction.store_id == store.id,
                and_(
                    models.Transaction.store_id.is_(None),
                    models.Transaction.store_name == store.name,
                ),
            ),
            models.Transaction.created_at >= month_start,
            models.Transaction.created_at < next_month,
        )
        .scalar()
        or 0
    )
    seoul_now = datetime.now(timezone(timedelta(hours=9)))
    settlement = (
        db.query(models.Settlement)
        .filter(
            models.Settlement.store_id == store.id,
            models.Settlement.year == seoul_now.year,
            models.Settlement.month == seoul_now.month,
        )
        .first()
    )
    settlement_status = (
        "completed" if settlement is not None and settlement.status == "completed" else "pending"
    )
    if settlement_status == "completed":
        settlement_expected = settlement.amount

    coupons = (
        db.query(models.Coupon)
        .filter(models.Coupon.store_id == store.id, models.Coupon.source == "owner")
        .all()
    )
    coupon_ids = [coupon.id for coupon in coupons]
    issued = used = 0
    if coupon_ids:
        issued = db.query(models.UserCoupon).filter(models.UserCoupon.coupon_id.in_(coupon_ids)).count()
        used = (
            db.query(models.UserCoupon)
            .filter(models.UserCoupon.coupon_id.in_(coupon_ids), models.UserCoupon.status == "used")
            .count()
        )

    has_unlimited = any(coupon.is_coupon_infinity or coupon.coupon_num is None for coupon in coupons if coupon.status == "active")
    finite_remaining = 0
    for coupon in coupons:
        if coupon.status != "active" or coupon.is_coupon_infinity or coupon.coupon_num is None:
            continue
        coupon_issued = db.query(models.UserCoupon).filter(models.UserCoupon.coupon_id == coupon.id).count()
        finite_remaining += max(coupon.coupon_num - coupon_issued, 0)

    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
    return schemas.OwnerDashboardResponse(
        store_id=store.id,
        store_name=store.name,
        settlement_expected=settlement_expected,
        settlement_status=settlement_status,
        settled_amount=settlement.amount if settlement_status == "completed" else 0,
        coupon_issued=issued,
        coupon_used=used,
        coupon_remaining=None if has_unlimited else finite_remaining,
        has_unlimited_coupon=has_unlimited,
        active_coupon_count=sum(coupon.status == "active" for coupon in coupons),
        stopped_coupon_count=sum(coupon.status == "stopped" for coupon in coupons),
        stamp_configured=policy is not None and policy.active,
    )


def coupon_json(
    coupon: models.Coupon,
    include_create_fields: bool = False,
    db: Session | None = None,
) -> dict:
    issued_count = (
        db.query(models.UserCoupon).filter(models.UserCoupon.coupon_id == coupon.id).count()
        if db is not None
        else 0
    )
    used_count = (
        db.query(models.UserCoupon)
        .filter(models.UserCoupon.coupon_id == coupon.id, models.UserCoupon.status == "used")
        .count()
        if db is not None
        else 0
    )
    remaining = (
        None
        if coupon.is_coupon_infinity or coupon.coupon_num is None
        else max(coupon.coupon_num - issued_count, 0)
    )
    common = {
        "id": coupon.id,
        "expiry_date": iso_z(coupon.valid_until) if coupon.valid_until else None,
        "title": coupon.title,
        "status": coupon.status,
        "issued_count": issued_count,
        "used_count": used_count,
        "remaining_quantity": remaining,
    }
    if include_create_fields:
        common |= {"target": coupon.target}
    if coupon.type == "discount_rate":
        return common | {"type": "percent", "sale_percent": coupon.value, "sale_max": coupon.max_discount,
                         "min_buy_price": coupon.min_payment, "coupon_num": coupon.coupon_num,
                         "is_coupon_infinity": coupon.is_coupon_infinity,
                         "is_apply_all": coupon.is_apply_all}
    return common | {"type": "fixed", "sale_price": coupon.value, "min_buy_price": coupon.min_payment,
                     "coupon_num": coupon.coupon_num, "is_coupon_infinity": coupon.is_coupon_infinity}


@router.post("/coupons", status_code=201)
def create_coupon(body: schemas.AdminCouponRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    if body.type == "stamp":
        policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
        if policy is None:
            policy = models.StampPolicy(store_id=store.id)
        policy.goal = body.stamp_max_require
        policy.reward = body.reward_content
        policy.condition = "방문 시 적립" if body.is_visit_stamp else "결제 시 적립"
        policy.expiry_date = body.expiry_date
        policy.active = True
        db.add(policy)
        db.commit(); db.refresh(policy)
        return {"id": policy.id, "type": "stamp", "goal": policy.goal, "reward": policy.reward,
                "condition": policy.condition,
                "expiry_date": iso_z(body.expiry_date) if body.expiry_date else None}
    now = utc_now()
    if not body.is_coupon_infinity and body.coupon_num is None:
        error(400, "coupon_quantity_required", "발급 수량을 입력해 주세요.")
    valid_until = body.expiry_date
    if valid_until is None and body.valid_days is not None:
        valid_until = now + timedelta(days=body.valid_days)
    if body.type == "percent":
        if body.sale_percent <= 0 or body.sale_percent > 100:
            error(400, "invalid_discount_rate", "할인율은 0보다 크고 100 이하여야 합니다.")
        coupon = models.Coupon(store_id=store.id, type="discount_rate",
            title=body.coupon_name or f"전 메뉴 {body.sale_percent:g}% 할인",
            value=round(body.sale_percent), target="전 메뉴" if body.is_apply_all else "일부 메뉴",
            valid_until=valid_until, min_payment=body.min_buy_price, max_discount=body.sale_max,
            coupon_num=body.coupon_num, is_coupon_infinity=body.is_coupon_infinity,
            is_apply_all=body.is_apply_all, status="active", created_at=now)
    else:
        if body.sale_price <= 0:
            error(400, "invalid_discount_amount", "할인 금액은 0보다 커야 합니다.")
        coupon = models.Coupon(store_id=store.id, type="discount_amount",
            title=body.coupon_name or f"{body.sale_price:,}원 할인",
            value=body.sale_price, target="전 메뉴", valid_until=valid_until,
            min_payment=body.min_buy_price, coupon_num=body.coupon_num,
            is_coupon_infinity=body.is_coupon_infinity, status="active", created_at=now)
    db.add(coupon); db.commit(); db.refresh(coupon)
    return coupon_json(coupon, include_create_fields=True, db=db)


@router.get("/coupons")
def list_coupons(owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    result = [
        coupon_json(c, db=db)
        for c in db.query(models.Coupon)
        .filter(models.Coupon.store_id == store.id, models.Coupon.source == "owner")
        .all()
    ]
    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
    if policy:
        result.append({"id": policy.id, "type": "stamp", "stamp_max_require": policy.goal,
                       "reward_content": policy.reward, "is_visit_stamp": policy.condition == "방문 시 적립",
                       "expiry_date": iso_z(policy.expiry_date) if policy.expiry_date else None})
    return result


def stop_coupon_row(coupon_id: int, owner_id: int, db: Session) -> models.Coupon:
    store = owner_store(db, owner_id)
    coupon = db.get(models.Coupon, coupon_id)
    if coupon and coupon.store_id == store.id and coupon.source == "owner":
        if coupon.status == "stopped":
            error(409, "coupon_already_stopped", "이미 발급 중단된 쿠폰입니다.")
        coupon.status = "stopped"
        coupon.stopped_at = utc_now()
        db.commit()
        return coupon
    error(404, "coupon_not_found", "쿠폰을 찾을 수 없습니다.")


@router.post("/coupons/{coupon_id}/stop")
def stop_coupon(coupon_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    return coupon_json(stop_coupon_row(coupon_id, owner_id, db), db=db)


@router.delete("/coupons/{coupon_id}", status_code=204)
def delete_coupon(coupon_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    stop_coupon_row(coupon_id, owner_id, db)
    return Response(status_code=204)


def stamp_policy_json(policy: models.StampPolicy | None) -> schemas.StampPolicyResponse:
    if policy is None:
        return schemas.StampPolicyResponse(configured=False, active=False)
    return schemas.StampPolicyResponse(
        configured=True,
        id=policy.id,
        goal=policy.goal,
        min_amount=policy.min_amount,
        completion_limit=policy.completion_limit,
        reward_name=policy.reward,
        reward_type=policy.reward_type,
        reward_value=policy.reward_value,
        reward_min_payment=policy.reward_min_payment,
        reward_max_discount=policy.reward_max_discount,
        reward_valid_days=policy.reward_valid_days,
        active=policy.active,
    )


@router.get("/stamp-policy", response_model=schemas.StampPolicyResponse)
def get_stamp_policy(owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
    return stamp_policy_json(policy)


@router.put("/stamp-policy", response_model=schemas.StampPolicyResponse)
def upsert_stamp_policy(
    body: schemas.StampPolicyRequest,
    owner_id: int = Depends(require_owner_id),
    db: Session = Depends(get_db),
):
    store = owner_store(db, owner_id)
    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
    if policy is None:
        policy = models.StampPolicy(store_id=store.id)
        db.add(policy)
    policy.goal = body.goal
    policy.min_amount = body.min_amount
    policy.completion_limit = body.completion_limit
    policy.reward = body.reward_name.strip()
    policy.reward_type = body.reward_type
    policy.reward_value = body.reward_value
    policy.reward_min_payment = body.reward_min_payment
    policy.reward_max_discount = body.reward_max_discount
    policy.reward_valid_days = body.reward_valid_days
    policy.condition = f"{body.min_amount:,}원 이상 결제 시"
    policy.active = body.active
    db.commit()
    db.refresh(policy)
    return stamp_policy_json(policy)


def menu_out(menu: models.Menu):
    return {"menuId": menu.id, "name": menu.name, "price": menu.price}


@router.post("/menus", status_code=201, response_model=schemas.MenuResponse)
def create_menu(body: schemas.MenuRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    if not body.name.strip() or body.price <= 0:
        error(400, "invalid_request", "메뉴 이름 또는 가격이 없습니다.")
    menu = models.Menu(store_id=owner_store(db, owner_id).id, name=body.name.strip(), price=body.price)
    db.add(menu); db.commit(); db.refresh(menu); return menu_out(menu)


@router.get("/menus", response_model=list[schemas.MenuResponse])
def list_menus(owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    return [menu_out(m) for m in db.query(models.Menu).filter(models.Menu.store_id == store.id).all()]


def owned_menu(db: Session, menu_id: int, store_id: int):
    menu = db.get(models.Menu, menu_id)
    if menu is None or menu.store_id != store_id:
        error(404, "menu_not_found", "메뉴를 찾을 수 없습니다.")
    return menu


@router.get("/menus/{menu_id}", response_model=schemas.MenuResponse)
def get_menu(menu_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    return menu_out(owned_menu(db, menu_id, owner_store(db, owner_id).id))


@router.patch("/menus/{menu_id}", response_model=schemas.MenuResponse)
def update_menu(menu_id: int, body: schemas.MenuUpdateRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    menu = owned_menu(db, menu_id, owner_store(db, owner_id).id)
    if body.name is not None: menu.name = body.name.strip()
    if body.price is not None: menu.price = body.price
    if not menu.name or menu.price <= 0: error(400, "invalid_request", "메뉴 이름 또는 가격이 없습니다.")
    db.commit(); db.refresh(menu); return menu_out(menu)


@router.delete("/menus/{menu_id}", status_code=204)
def delete_menu(menu_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    menu = owned_menu(db, menu_id, owner_store(db, owner_id).id)
    db.delete(menu); db.commit(); return Response(status_code=204)


def qr_out(qr: models.PaymentQr, status_field=False):
    data = {"qrId": qr.id, "token": qr.token, "type": qr.type, "amount": qr.amount,
            "qrImage": qr.qr_image, "expiresAt": qr.expires_at}
    return data | ({"status": qr.status} if status_field else {})


def create_qr(db: Session, store_id: int, amount: int | None, qr_type: str = "payment"):
    if qr_type == "payment" and (amount is None or amount <= 0):
        error(400, "invalid_request", "결제 금액은 0보다 커야 합니다.")
    qr = models.PaymentQr(
        store_id=store_id,
        type=qr_type,
        amount=amount,
        qr_image="",
        expires_at=utc_now() + timedelta(minutes=PAYMENT_QR_TTL_MINUTES),
    )
    db.add(qr); db.flush(); qr.qr_image = f"/admin/qrs/{qr.id}/image"; db.commit(); db.refresh(qr)
    return qr


def validate_stamp_amount(db: Session, store_id: int, amount: int | None) -> models.StampPolicy:
    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store_id).first()
    if policy is None or not policy.active:
        error(409, "stamp_not_configured", "매장에서 스탬프 설정을 완료해주세요!")
    if amount is None or amount <= 0:
        error(400, "invalid_stamp_amount", "적립 대상 금액을 입력해 주세요.")
    if amount < policy.min_amount:
        error(400, "stamp_minimum_not_met", "기준 금액을 충족하지 못했습니다.")
    return policy


@router.post("/qrs/menu", status_code=201, response_model=schemas.QrCreateResponse)
def menu_qr(body: schemas.MenuQrRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    if not body.menuIds: error(400, "invalid_request", "메뉴를 선택해 주세요.")
    menus = [owned_menu(db, menu_id, store.id) for menu_id in body.menuIds]
    amount = sum(m.price for m in menus)
    if body.qr_type == "stamp":
        validate_stamp_amount(db, store.id, amount)
    return qr_out(create_qr(db, store.id, amount, qr_type=body.qr_type))


@router.post("/qrs/direct", status_code=201, response_model=schemas.QrCreateResponse)
def direct_qr(body: schemas.DirectQrRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id); return qr_out(create_qr(db, store.id, body.amount))


@router.post("/qrs/stamp", status_code=201, response_model=schemas.QrCreateResponse)
def stamp_qr(body: schemas.StampQrRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    """스탬프 적립용 QR 생성. 손님이 이 QR을 스캔하면 POST /scan이 스탬프를 적립시킨다."""
    store = owner_store(db, owner_id)
    if body.amount is not None and body.menuIds:
        error(400, "invalid_request", "직접 입력 금액과 메뉴 선택은 동시에 사용할 수 없습니다.")
    amount = body.amount
    if body.menuIds:
        menus = [owned_menu(db, menu_id, store.id) for menu_id in body.menuIds]
        amount = sum(menu.price for menu in menus)
    validate_stamp_amount(db, store.id, amount)
    return qr_out(create_qr(db, store.id, amount, qr_type="stamp"))


def owned_qr(db: Session, qr_id: int, store_id: int):
    qr = db.get(models.PaymentQr, qr_id)
    if qr is None or qr.store_id != store_id: error(404, "qr_not_found", "QR을 찾을 수 없습니다.")
    if qr.status in {"WAITING", "SCANNED"} and qr.expires_at is not None and utc_now() > qr.expires_at:
        qr.status = "EXPIRED"
        db.commit()
    return qr


@router.get("/qrs/{qr_id}", response_model=schemas.QrResponse)
def get_qr(qr_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    return qr_out(owned_qr(db, qr_id, owner_store(db, owner_id).id), True)


@router.get("/qrs/{qr_id}/image", response_class=StreamingResponse)
def get_qr_image(qr_id: int, db: Session = Depends(get_db)):
    """QR 토큰을 실제로 스캔할 수 있는 SVG 이미지를 반환한다.

    이 엔드포인트는 점주 화면의 <img>가 Bearer 헤더 없이도 이미지를
    불러올 수 있도록 공개한다. QR 자체가 결제/적립 플로우의 공개 진입점이며,
    실제 사용 시에는 토큰 상태·만료·사용자 인증을 /scan과 /checkout에서 검증한다.
    """
    qr = db.get(models.PaymentQr, qr_id)
    if qr is None:
        error(404, "qr_not_found", "QR을 찾을 수 없습니다.")

    # SVG 생성은 Pillow가 필요 없는 qrcode의 SVG factory를 사용한다.
    import qrcode
    from qrcode.image.svg import SvgPathImage

    image = qrcode.make(qr.token, image_factory=SvgPathImage, box_size=10, border=4)
    output = BytesIO()
    image.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/qrs/{qr_id}/result", response_model=schemas.PaymentQrResultResponse)
def get_qr_result(qr_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    qr = owned_qr(db, qr_id, store.id)
    payment = db.query(models.Payment).filter(models.Payment.qr_id == qr.id).first()
    return schemas.PaymentQrResultResponse(
        qrId=qr.id,
        status=qr.status,
        amount=qr.amount,
        paymentId=payment.id if payment else None,
        paidAmount=payment.amount if payment else None,
        discountAmount=payment.discount_amount if payment else None,
        benefitSummary=payment.benefit_summary if payment else None,
        completedAt=payment.completed_at if payment else None,
    )


@router.delete("/qrs/{qr_id}", status_code=204)
def delete_qr(qr_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    qr = owned_qr(db, qr_id, owner_store(db, owner_id).id); db.delete(qr); db.commit(); return Response(status_code=204)


@router.get("/payments/{payment_id}", response_model=schemas.PaymentResponse)
def get_payment(payment_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id); payment = db.get(models.Payment, payment_id)
    if payment is None or payment.store_id != store.id: error(404, "payment_not_found", "결제 정보를 찾을 수 없습니다.")
    return {"paymentId": payment.id, "amount": payment.amount, "status": payment.status,
            "originalAmount": payment.original_amount, "discountAmount": payment.discount_amount,
            "benefitSummary": payment.benefit_summary, "completedAt": payment.completed_at}


@router.get("/stamps/{stamp_id}", response_model=schemas.AdminStampResponse)
def get_stamp(stamp_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id); card = db.get(models.StampCard, stamp_id)
    if card is None or card.store_id != store.id: error(404, "stamp_not_found", "스탬프 정보를 찾을 수 없습니다.")
    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
    return {"shopName": store.name, "currentStamp": card.current, "maxStamp": policy.goal if policy else 0}
