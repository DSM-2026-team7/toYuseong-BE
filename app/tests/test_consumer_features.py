from datetime import timedelta

from app import database, models
from app.routers import auth as auth_router
from app.routers import checkout as checkout_router
from app.routers import passes as passes_router
from app.utils import utc_now


USER_HEADERS = {"X-User-Id": "100"}


def _confirmed(payment_key: str, order_id: str, amount: int) -> dict:
    return {
        "paymentKey": payment_key,
        "orderId": order_id,
        "totalAmount": amount,
        "status": "DONE",
        "method": "카드",
    }


def test_google_onboarding_preferences_and_role_switch(client, monkeypatch):
    monkeypatch.setattr(
        auth_router,
        "verify_google_credential",
        lambda credential: {
            "sub": "google-user-123",
            "email": "consumer@example.com",
            "name": "구글 사용자",
            "picture": "https://example.com/profile.png",
        },
    )

    login = client.post("/auth/google", json={"credential": "verified-id-token"})
    assert login.status_code == 200
    body = login.json()
    assert body["is_new"] is True
    assert body["requires_role_selection"] is True
    assert body["roles"] == []
    bearer = {"Authorization": f"Bearer {body['token']}"}

    selected = client.post(
        "/auth/role",
        json={"role": "customer", "region": "유성구 궁동"},
        headers=bearer,
    )
    assert selected.status_code == 200
    assert selected.json()["roles"] == ["customer"]

    preferences = client.patch(
        "/me/preferences",
        json={"location_permission": "granted"},
        headers=bearer,
    )
    assert preferences.status_code == 200
    assert preferences.json()["location_permission"] == "granted"
    assert preferences.json()["region"] == "유성구 궁동"

    owner = client.patch("/me/role", json={"role": "owner"}, headers=bearer)
    assert owner.status_code == 200
    assert owner.json()["roles"] == ["customer", "owner"]
    assert owner.json()["store_verification_required"] is True

    registered = client.post(
        "/admin/register",
        headers=bearer,
        json={
            "name": "구글 사용자 가게",
                "register_num": "987-65-43210",
                "category": "cafe",
                "address": "대전 유성구 궁동 10",
                "region": "유성구 궁동",
            "phone_no": "010-1111-2222",
        },
    )
    assert registered.status_code == 201
    assert registered.json()["status"] == "pending"
    assert client.get("/me", headers=bearer).json()["store_verification"] == "pending"

    switched_back = client.patch("/me/role", json={"role": "customer"}, headers=bearer)
    assert switched_back.status_code == 200
    assert switched_back.json()["roles"] == ["customer", "owner"]

    second_login = client.post("/auth/google", json={"credential": "verified-id-token"})
    assert second_login.status_code == 200
    assert second_login.json()["user_id"] == body["user_id"]
    assert second_login.json()["is_new"] is False


def test_store_search_map_and_detail_include_consumer_data(client):
    search = client.get(
        "/stores",
        params={
            "q": "커피",
            "latitude": 36.3551,
            "longitude": 127.3412,
            "sort": "distance",
        },
        headers=USER_HEADERS,
    )
    assert search.status_code == 200
    stores = search.json()["stores"]
    assert stores
    assert all("커피" in store["name"] for store in stores)
    assert stores[0]["distance_km"] == 0
    assert stores[0]["address"]
    assert stores[0]["latitude"] is not None

    detail = client.get("/stores/3", headers=USER_HEADERS)
    assert detail.status_code == 200
    assert detail.json()["phone_no"] == "042-000-0003"
    assert detail.json()["address"]
    assert len(detail.json()["coupons"]) >= 2
    assert detail.json()["stamp"]["goal"] == 5


def test_coupon_quantity_and_expired_coupon_deletion(client):
    db = database.SessionLocal()
    try:
        db.add(models.User(id=101, nickname="다른 사용자", region="유성구 궁동", role="customer"))
        limited = models.Coupon(
            store_id=1,
            type="discount_amount",
            title="선착순 쿠폰",
            value=1000,
            target="전 메뉴",
            valid_until=utc_now() + timedelta(days=1),
            store_only=True,
            min_payment=0,
            coupon_num=1,
            is_coupon_infinity=False,
        )
        expired = models.Coupon(
            store_id=1,
            type="discount_amount",
            title="만료 쿠폰",
            value=1000,
            target="전 메뉴",
            valid_until=utc_now() - timedelta(hours=1),
            store_only=True,
            min_payment=0,
        )
        db.add_all([limited, expired])
        db.flush()
        db.add(
            models.UserCoupon(
                user_id=100,
                coupon_id=expired.id,
                status="active",
                claimed_at=utc_now() - timedelta(days=2),
            )
        )
        db.commit()
        limited_id = limited.id
        expired_coupon_id = expired.id
    finally:
        db.close()

    first = client.post(f"/coupons/{limited_id}/claim", headers=USER_HEADERS)
    assert first.status_code == 201
    sold_out = client.post(f"/coupons/{limited_id}/claim", headers={"X-User-Id": "101"})
    assert sold_out.status_code == 409
    assert sold_out.json()["error"] == "coupon_sold_out"

    expired_list = client.get("/me/coupons", params={"status": "expired"}, headers=USER_HEADERS)
    expired_item = next(
        item for item in expired_list.json()["coupons"] if item["title"] == "만료 쿠폰"
    )
    owned_items = client.get("/me/coupons", headers=USER_HEADERS).json()["coupons"]
    assert any(item["title"] == "만료 쿠폰" for item in owned_items)
    deleted = client.delete(
        f"/me/coupons/{expired_item['user_coupon_id']}",
        headers=USER_HEADERS,
    )
    assert deleted.status_code == 204
    all_items = client.get("/me/coupons", params={"status": "all"}, headers=USER_HEADERS)
    assert all(item["title"] != "만료 쿠폰" for item in all_items.json()["coupons"])

    # 원본 쿠폰은 삭제하지 않고 사용자 쿠폰함에서만 숨긴다.
    db = database.SessionLocal()
    try:
        assert db.get(models.Coupon, expired_coupon_id) is not None
    finally:
        db.close()


def test_stamp_daily_limit_is_global_across_stores(client):
    first_qr = client.post("/admin/qrs/stamp", headers={"Authorization": "Bearer 1"}, json={"amount": 5000})
    second_qr = client.post("/admin/qrs/stamp", headers={"Authorization": "Bearer 2"}, json={"amount": 5000})

    first = client.post("/scan", headers=USER_HEADERS, json={"qr_token": first_qr.json()["token"]})
    assert first.status_code == 200
    second = client.post("/scan", headers=USER_HEADERS, json={"qr_token": second_qr.json()["token"]})
    assert second.status_code == 409
    assert second.json()["error"] == "already_stamped_today"

    # 오늘 다른 매장에서 적립했어도 상세의 일일 한도 상태는 동일하게 보인다.
    other_store = client.get("/stores/2", headers=USER_HEADERS)
    assert other_store.json()["stamp"]["stamped_today"] is True


def test_payment_qr_is_consumed_after_checkout_and_auto_earns_stamp(client, monkeypatch):
    monkeypatch.setattr(checkout_router, "confirm_toss_payment", _confirmed)
    created = client.post(
        "/admin/qrs/direct",
        headers={"Authorization": "Bearer 1"},
        json={"amount": 18000},
    )
    token = created.json()["token"]
    qr_id = created.json()["qrId"]

    scan = client.post("/scan", headers=USER_HEADERS, json={"qr_token": token})
    assert scan.status_code == 200
    assert client.get(f"/admin/qrs/{qr_id}", headers={"Authorization": "Bearer 1"}).json()["status"] == "SCANNED"

    paid = client.post(
        "/checkout",
        headers=USER_HEADERS,
        json={
            "store_id": 1,
            "amount": 18000,
            "benefit_id": "none",
            "method": "card",
            "paymentKey": "payment-qr-key",
            "orderId": "payment-qr-order",
            "payment_amount": 18000,
            "qr_token": token,
        },
    )
    assert paid.status_code == 200
    assert paid.json()["stamp"]["earned"] is True
    assert client.get(f"/admin/qrs/{qr_id}", headers={"Authorization": "Bearer 1"}).json()["status"] == "CONSUMED"

    db = database.SessionLocal()
    try:
        payment = db.query(models.Payment).filter(models.Payment.qr_id == qr_id).one()
        assert payment.amount == 18000
        assert (
            db.query(models.Transaction)
            .filter(models.Transaction.user_id == 100, models.Transaction.type == "stamp_earn")
            .count()
            == 1
        )
    finally:
        db.close()


def test_coupon_and_pass_can_be_applied_together_with_pass_limit(client, monkeypatch):
    monkeypatch.setattr(checkout_router, "confirm_toss_payment", _confirmed)
    claimed = client.post("/coupons/1/claim", headers=USER_HEADERS)
    assert claimed.status_code == 201

    db = database.SessionLocal()
    try:
        user_pass = models.UserPass(
            user_id=100,
            pass_id=1,
            status="active",
            purchased_at=utc_now(),
            expires_at=utc_now() + timedelta(days=1),
            discount_used=0,
            discount_limit=10000,
        )
        db.add(user_pass)
        db.commit()
        db.refresh(user_pass)
        user_pass_id = user_pass.id
    finally:
        db.close()

    benefit_ids = [f"coupon:{claimed.json()['user_coupon_id']}", f"pass:{user_pass_id}"]
    quote = client.post(
        "/checkout/quote",
        headers=USER_HEADERS,
        json={"store_id": 3, "amount": 10000, "benefit_ids": benefit_ids},
    )
    assert quote.status_code == 200
    assert quote.json()["total_discount"] == 2000
    assert quote.json()["final_amount"] == 8000

    checkout = client.post(
        "/checkout",
        headers=USER_HEADERS,
        json={
            "store_id": 3,
            "amount": 10000,
            "benefit_ids": benefit_ids,
            "method": "card",
            "paymentKey": "combined-payment-key",
            "orderId": "combined-order-id",
            "payment_amount": 8000,
        },
    )
    assert checkout.status_code == 200
    assert checkout.json()["benefit_kind"] == "coupon_rate+pass"
    assert len(checkout.json()["applied_benefits"]) == 2

    my_pass = client.get("/me/passes", headers=USER_HEADERS).json()["passes"][0]
    assert my_pass["discount_used"] == 1000
    assert my_pass["remaining_discount"] == 9000
    history = client.get("/me/transactions", params={"filter": "benefit"}, headers=USER_HEADERS)
    assert {item["type"] for item in history.json()["transactions"]} == {"coupon_use", "pass_use"}


def test_repurchase_extends_existing_pass_and_discount_limit(client, monkeypatch):
    monkeypatch.setattr(passes_router, "confirm_toss_payment", _confirmed)
    first = client.post(
        "/passes/2/purchase",
        headers=USER_HEADERS,
        json={
            "duration_days": 30,
            "paymentKey": "extend-pass-key-1",
            "orderId": "extend-pass-order-1",
            "amount": 9900,
        },
    )
    second = client.post(
        "/passes/2/purchase",
        headers=USER_HEADERS,
        json={
            "duration_days": 30,
            "paymentKey": "extend-pass-key-2",
            "orderId": "extend-pass-order-2",
            "amount": 9900,
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["extended"] is False
    assert second.json()["extended"] is True
    assert second.json()["user_pass_id"] == first.json()["user_pass_id"]
    assert second.json()["discount_limit"] == 60000

    db = database.SessionLocal()
    try:
        assert (
            db.query(models.UserPass)
            .filter(models.UserPass.user_id == 100, models.UserPass.pass_id == 2)
            .count()
            == 1
        )
    finally:
        db.close()
