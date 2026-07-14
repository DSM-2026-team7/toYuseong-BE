from app import database, models


AUTH = {"Authorization": "Bearer 1"}


def test_admin_requires_authentication(client):
    response = client.get("/admin/shop")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_admin_menu_and_qr_flow(client):
    created = client.post("/admin/menus", headers=AUTH, json={"name": "아메리카노", "price": 4500})
    assert created.status_code == 201
    menu_id = created.json()["menuId"]

    assert client.get("/admin/menus", headers=AUTH).json() == [
        {"menuId": menu_id, "name": "아메리카노", "price": 4500}
    ]
    updated = client.patch(f"/admin/menus/{menu_id}", headers=AUTH, json={"price": 5000})
    assert updated.json()["price"] == 5000

    qr = client.post("/admin/qrs/menu", headers=AUTH, json={"menuIds": [menu_id]})
    assert qr.status_code == 201
    assert qr.json()["amount"] == 5000
    qr_id = qr.json()["qrId"]
    assert client.get(f"/admin/qrs/{qr_id}", headers=AUTH).json()["status"] == "WAITING"


def test_admin_coupon_flow(client):
    created = client.post("/admin/coupons", headers=AUTH, json={
        "type": "fixed", "sale_price": 3000, "min_buy_price": 15000,
        "coupon_num": 100, "is_coupon_infinity": False,
        "expiry_date": "2026-09-30T23:59:59Z",
    })
    assert created.status_code == 201
    assert created.json()["type"] == "fixed"
    assert created.json()["sale_price"] == 3000
    assert created.json()["title"] == "3,000원 할인"
    assert created.json()["target"] == "전 메뉴"
    assert created.json()["expiry_date"] == "2026-09-30T23:59:59Z"
    coupon_id = created.json()["id"]
    assert any(item["id"] == coupon_id for item in client.get("/admin/coupons", headers=AUTH).json())
    assert client.delete(f"/admin/coupons/{coupon_id}", headers=AUTH).status_code == 204


def test_admin_stamp_policy_preserves_expiry_date(client):
    created = client.post("/admin/coupons", headers=AUTH, json={
        "type": "stamp", "stamp_max_require": 10,
        "reward_content": "아메리카노 1잔 무료", "is_visit_stamp": False,
        "expiry_date": "2026-12-31T23:59:59Z",
    })
    assert created.status_code == 201
    assert created.json()["expiry_date"] == "2026-12-31T23:59:59Z"

    policies = [item for item in client.get("/admin/coupons", headers=AUTH).json()
                if item["type"] == "stamp"]
    assert policies[0]["expiry_date"] == "2026-12-31T23:59:59Z"


def test_validation_errors_follow_common_error_shape(client):
    response = client.post("/admin/menus", headers=AUTH, json={})
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request", "message": "잘못된 요청입니다."}


def test_register_shop_and_duplicate_business_number(client):
    db = database.SessionLocal()
    db.add(models.User(id=999, nickname="새 사장님", region="유성구", role="owner"))
    db.commit(); db.close()
    headers = {"Authorization": "Bearer owner-999"}
    body = {"name": "새 가게", "register_num": "123-45-67890", "category": "cafe",
            "address": "대전 유성구 궁동 1", "region": "유성구 궁동",
            "phone_no": "010-1234-5678"}
    first = client.post("/admin/register", headers=headers, json=body)
    assert first.status_code == 201
    assert first.json()["status"] == "pending"
    assert client.post("/admin/register", headers=headers, json=body).status_code == 409
