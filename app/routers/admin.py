from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.utils import iso_z, require_owner_id

router = APIRouter(prefix="/admin", tags=["admin"])


def error(code: int, name: str, message: str):
    raise HTTPException(code, detail={"error": name, "message": message})


def owner_store(db: Session, owner_id: int) -> models.Store:
    store = db.query(models.Store).filter(models.Store.owner_id == owner_id).first()
    if store is None:
        error(404, "shop_not_found", "등록된 매장이 없습니다.")
    return store


@router.post("/register", status_code=201, response_model=schemas.AdminStoreResponse)
def register_shop(body: schemas.AdminRegisterRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    if db.query(models.Store).filter(models.Store.register_num == body.register_num).first():
        error(409, "already_registered", "이미 등록된 사업자입니다.")
    if db.query(models.Store).filter(models.Store.owner_id == owner_id).first():
        error(409, "already_registered", "이미 등록된 사업자입니다.")
    data = body.model_dump()
    data["business_hours"] = body.business_hours or ""
    store = models.Store(owner_id=owner_id, **data)
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


@router.get("/shop", response_model=schemas.AdminStoreResponse)
def get_shop(owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    return owner_store(db, owner_id)


def coupon_json(coupon: models.Coupon, include_create_fields: bool = False) -> dict:
    common = {
        "id": coupon.id,
        "expiry_date": iso_z(coupon.valid_until) if coupon.valid_until else None,
    }
    if include_create_fields:
        common |= {"title": coupon.title, "target": coupon.target}
    if coupon.type == "discount_rate":
        return common | {"type": "percent", "sale_percent": coupon.value, "sale_max": coupon.max_discount,
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
        db.add(policy)
        db.commit(); db.refresh(policy)
        return {"id": policy.id, "type": "stamp", "goal": policy.goal, "reward": policy.reward,
                "condition": policy.condition, "expiry_date": iso_z(body.expiry_date)}
    if body.type == "percent":
        coupon = models.Coupon(store_id=store.id, type="discount_rate", title=f"전 메뉴 {body.sale_percent:g}% 할인",
            value=round(body.sale_percent), target="전 메뉴" if body.is_apply_all else "일부 메뉴",
            valid_until=body.expiry_date, max_discount=body.sale_max, is_apply_all=body.is_apply_all)
    else:
        coupon = models.Coupon(store_id=store.id, type="discount_amount", title=f"{body.sale_price:,}원 할인",
            value=body.sale_price, target="전 메뉴", valid_until=body.expiry_date,
            min_payment=body.min_buy_price, coupon_num=body.coupon_num,
            is_coupon_infinity=body.is_coupon_infinity)
    db.add(coupon); db.commit(); db.refresh(coupon)
    return coupon_json(coupon, include_create_fields=True)


@router.get("/coupons")
def list_coupons(owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    result = [coupon_json(c) for c in db.query(models.Coupon).filter(models.Coupon.store_id == store.id).all()]
    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
    if policy:
        result.append({"id": policy.id, "type": "stamp", "stamp_max_require": policy.goal,
                       "reward_content": policy.reward, "is_visit_stamp": policy.condition == "방문 시 적립",
                       "expiry_date": iso_z(policy.expiry_date) if policy.expiry_date else None})
    return result


@router.delete("/coupons/{coupon_id}", status_code=204)
def delete_coupon(coupon_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    coupon = db.get(models.Coupon, coupon_id)
    if coupon and coupon.store_id == store.id:
        db.delete(coupon); db.commit(); return Response(status_code=204)
    policy = db.get(models.StampPolicy, coupon_id)
    if policy and policy.store_id == store.id:
        db.delete(policy); db.commit(); return Response(status_code=204)
    error(404, "coupon_not_found", "쿠폰을 찾을 수 없습니다.")


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
    data = {"qrId": qr.id, "amount": qr.amount, "qrImage": qr.qr_image}
    return data | ({"status": qr.status} if status_field else {})


def create_qr(db: Session, store_id: int, amount: int):
    if amount <= 0: error(400, "invalid_request", "결제 금액은 0보다 커야 합니다.")
    qr = models.PaymentQr(store_id=store_id, amount=amount, qr_image="")
    db.add(qr); db.flush(); qr.qr_image = f"/admin/qrs/{qr.id}/image"; db.commit(); db.refresh(qr)
    return qr


@router.post("/qrs/menu", status_code=201, response_model=schemas.QrCreateResponse)
def menu_qr(body: schemas.MenuQrRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id)
    if not body.menuIds: error(400, "invalid_request", "메뉴를 선택해 주세요.")
    menus = [owned_menu(db, menu_id, store.id) for menu_id in body.menuIds]
    return qr_out(create_qr(db, store.id, sum(m.price for m in menus)))


@router.post("/qrs/direct", status_code=201, response_model=schemas.QrCreateResponse)
def direct_qr(body: schemas.DirectQrRequest, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id); return qr_out(create_qr(db, store.id, body.amount))


def owned_qr(db: Session, qr_id: int, store_id: int):
    qr = db.get(models.PaymentQr, qr_id)
    if qr is None or qr.store_id != store_id: error(404, "qr_not_found", "QR을 찾을 수 없습니다.")
    return qr


@router.get("/qrs/{qr_id}", response_model=schemas.QrResponse)
def get_qr(qr_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    return qr_out(owned_qr(db, qr_id, owner_store(db, owner_id).id), True)


@router.delete("/qrs/{qr_id}", status_code=204)
def delete_qr(qr_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    qr = owned_qr(db, qr_id, owner_store(db, owner_id).id); db.delete(qr); db.commit(); return Response(status_code=204)


@router.get("/payments/{payment_id}", response_model=schemas.PaymentResponse)
def get_payment(payment_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id); payment = db.get(models.Payment, payment_id)
    if payment is None or payment.store_id != store.id: error(404, "payment_not_found", "결제 정보를 찾을 수 없습니다.")
    return {"paymentId": payment.id, "amount": payment.amount, "status": payment.status}


@router.get("/stamps/{stamp_id}", response_model=schemas.AdminStampResponse)
def get_stamp(stamp_id: int, owner_id: int = Depends(require_owner_id), db: Session = Depends(get_db)):
    store = owner_store(db, owner_id); card = db.get(models.StampCard, stamp_id)
    if card is None or card.store_id != store.id: error(404, "stamp_not_found", "스탬프 정보를 찾을 수 없습니다.")
    policy = db.query(models.StampPolicy).filter(models.StampPolicy.store_id == store.id).first()
    return {"shopName": store.name, "currentStamp": card.current, "maxStamp": policy.goal if policy else 0}
