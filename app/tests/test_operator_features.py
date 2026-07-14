from datetime import timedelta

from app import database, models
from app.routers import checkout as checkout_router
from app.routers import passes as passes_router
from app.utils import utc_now
from web.auth import create_token


CUSTOMER = {"X-User-Id": "100"}


def _admin_headers() -> dict[str, str]:
    token = create_token(1, "admin", must_change_password=False)
    return {"Authorization": f"Bearer {token}"}


def _confirmed(payment_key: str, order_id: str, amount: int) -> dict:
    return {
        "paymentKey": payment_key,
        "orderId": order_id,
        "totalAmount": amount,
        "status": "DONE",
        "method": "카드",
    }


def test_shared_admin_login_forces_initial_password_reset(client):
    login = client.post(
        "/admin/auth/login",
        json={"username": "admin", "password": "admin1234"},
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    blocked_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    blocked = client.get("/admin/dashboard", headers=blocked_headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "password_change_required"

    changed = client.post(
        "/admin/auth/change-password",
        headers=blocked_headers,
        json={"new_password": "new-admin-password"},
    )
    assert changed.status_code == 200
    headers = {"Authorization": f"Bearer {changed.json()['token']}"}
    assert client.get("/admin/dashboard", headers=headers).status_code == 200

    relogin = client.post(
        "/admin/auth/login",
        json={"username": "admin", "password": "new-admin-password"},
    )
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is False


def test_dashboard_counts_pending_stores_and_only_current_month_pass_subsidy(client):
    db = database.SessionLocal()
    try:
        db.add(
            models.StoreApplication(
                name="심사 대기 매장",
                category="cafe",
                region="유성구 궁동",
                business_number="222-33-44444",
                business_hours="09:00-20:00",
                phone="042-222-3333",
                applicant_name="신청자",
                address="대전 유성구 궁동 1",
                status="pending",
            )
        )
        db.add_all(
            [
                models.Transaction(
                    user_id=100,
                    store_id=1,
                    store_name="동네커피 유성점",
                    type="pass_use",
                    amount=-1200,
                    discount_rate=10,
                    created_at=utc_now(),
                ),
                models.Transaction(
                    user_id=100,
                    store_id=1,
                    store_name="동네커피 유성점",
                    type="coupon_use",
                    amount=-9000,
                    created_at=utc_now(),
                ),
                models.Transaction(
                    user_id=100,
                    store_id=1,
                    store_name="동네커피 유성점",
                    type="pass_use",
                    amount=-5000,
                    discount_rate=10,
                    created_at=utc_now() - timedelta(days=40),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    dashboard = client.get("/admin/dashboard", headers=_admin_headers())
    assert dashboard.status_code == 200
    assert dashboard.json()["pending_applications"] == 1
    assert dashboard.json()["stats"]["estimated_subsidy"] == 1200


def test_rejected_store_can_resubmit_and_blank_reason_is_rejected(client):
    db = database.SessionLocal()
    try:
        db.add(
            models.User(
                id=999,
                nickname="재신청 사장님",
                region="유성구",
                role="owner",
                owner_enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()
    owner = {"Authorization": "Bearer owner-999"}
    body = {
        "name": "재신청 매장",
        "register_num": "333-44-55555",
        "category": "cafe",
        "address": "대전 유성구 궁동 3",
        "phone_no": "042-333-4444",
    }
    registered = client.post("/admin/register", headers=owner, json=body)
    application_id = registered.json()["application_id"]

    blank = client.post(
        f"/admin/applications/{application_id}/reject",
        headers=_admin_headers(),
        json={"reason": "   "},
    )
    assert blank.status_code == 400

    rejected = client.post(
        f"/admin/applications/{application_id}/reject",
        headers=_admin_headers(),
        json={"reason": "사업자 정보 확인 필요"},
    )
    assert rejected.status_code == 200
    verification = client.get("/admin/verification", headers=owner).json()
    assert verification["status"] == "none"
    assert verification["reject_reason"] == "사업자 정보 확인 필요"

    reapplied = client.post("/admin/register", headers=owner, json=body)
    assert reapplied.status_code == 201
    assert reapplied.json()["status"] == "pending"
    assert reapplied.json()["application_id"] != application_id


def test_pass_update_and_delete_do_not_change_owned_pass_terms(client, monkeypatch):
    monkeypatch.setattr(passes_router, "confirm_toss_payment", _confirmed)
    monkeypatch.setattr(checkout_router, "confirm_toss_payment", _confirmed)
    admin = _admin_headers()
    created = client.post(
        "/admin/passes",
        headers=admin,
        json={
            "name": "구매 당시 패스",
            "duration_days": 30,
            "price": 5000,
            "max_discount_amount": 50000,
        },
    )
    assert created.status_code == 201
    pass_id = created.json()["id"]
    listed = client.get("/admin/passes", headers=admin).json()["passes"]
    item = next(item for item in listed if item["id"] == pass_id)
    assert item["duration_days"] == 30
    assert item["price"] == 5000
    assert item["max_discount_amount"] == 50000

    purchased = client.post(
        f"/passes/{pass_id}/purchase",
        headers=CUSTOMER,
        json={
            "duration_days": 30,
            "paymentKey": "snapshot-pass-key",
            "orderId": "snapshot-pass-order",
            "amount": 5000,
        },
    )
    assert purchased.status_code == 201

    updated = client.put(
        f"/admin/passes/{pass_id}",
        headers=admin,
        json={
            "name": "수정된 패스",
            "scope": "store",
            "scope_store_id": 6,
            "discount_rate": 20,
            "target_desc": "다른 매장 20% 할인",
            "price_tiers": [{"duration_days": 30, "price": 9000}],
            "max_discount_amount": 100000,
            "sale_status": "on_sale",
        },
    )
    assert updated.status_code == 200
    assert client.delete(f"/admin/passes/{pass_id}", headers=admin).status_code == 200

    public_pass_ids = {item["id"] for item in client.get("/passes").json()["passes"]}
    assert pass_id not in public_pass_ids
    my_pass = next(
        item
        for item in client.get("/me/passes", headers=CUSTOMER).json()["passes"]
        if item["user_pass_id"] == purchased.json()["user_pass_id"]
    )
    assert my_pass["name"] == "구매 당시 패스"
    assert my_pass["discount_rate"] == 10
    assert my_pass["discount_limit"] == 50000

    benefits = client.get(
        "/checkout/benefits",
        headers=CUSTOMER,
        params={"store_id": 1, "amount": 10000},
    ).json()["benefits"]
    owned_pass_benefit = next(item for item in benefits if item["benefit_id"].startswith("pass:"))
    assert owned_pass_benefit["title"] == "구매 당시 패스"
    assert owned_pass_benefit["discount"] == 1000


def test_monthly_settlement_is_pass_only_locked_and_supports_batch(client):
    admin = _admin_headers()
    now = utc_now()
    db = database.SessionLocal()
    try:
        db.add_all(
            [
                models.Transaction(
                    user_id=100,
                    store_id=1,
                    store_name="동네커피 유성점",
                    type="pass_use",
                    amount=-1000,
                    discount_rate=10,
                    memo="패스 할인",
                    created_at=now,
                ),
                models.Transaction(
                    user_id=100,
                    store_id=1,
                    store_name="동네커피 유성점",
                    type="coupon_use",
                    amount=-8000,
                    memo="쿠폰 할인",
                    created_at=now,
                ),
                models.Transaction(
                    user_id=100,
                    store_id=3,
                    store_name="우리분식",
                    type="pass_use",
                    amount=-700,
                    discount_rate=10,
                    memo="패스 할인",
                    created_at=now,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    current = client.get("/admin/settlements", headers=admin)
    assert current.status_code == 200
    assert current.json()["stats"]["total_subsidy"] == 1700
    store1 = next(item for item in current.json()["stores"] if item["store_id"] == 1)
    assert store1["transaction_count"] == 1
    assert store1["subsidy_amount"] == 1000

    processed = client.post("/admin/settlements/1/process", headers=admin)
    assert processed.status_code == 200
    assert processed.json()["amount"] == 1000
    assert processed.json()["transaction_count"] == 1

    owner_dashboard = client.get(
        "/admin/owner/dashboard",
        headers={"Authorization": "Bearer 1"},
    )
    assert owner_dashboard.json()["settlement_status"] == "completed"
    assert owner_dashboard.json()["settled_amount"] == 1000

    # 지급완료 후 같은 월에 데이터가 추가돼도 완료 내역은 잠긴다.
    db = database.SessionLocal()
    try:
        db.add(
            models.Transaction(
                user_id=100,
                store_id=1,
                store_name="동네커피 유성점",
                type="pass_use",
                amount=-999,
                discount_rate=10,
                created_at=utc_now() + timedelta(seconds=1),
            )
        )
        db.commit()
    finally:
        db.close()

    locked = client.get("/admin/settlements", headers=admin).json()
    locked_store1 = next(item for item in locked["stores"] if item["store_id"] == 1)
    assert locked_store1["status"] == "completed"
    assert locked_store1["subsidy_amount"] == 1000
    assert locked_store1["transaction_count"] == 1
    assert client.post("/admin/settlements/1/process", headers=admin).status_code == 409

    batch = client.post("/admin/settlements/process-all", headers=admin)
    assert batch.status_code == 200
    assert batch.json()["processed_store_count"] == 1
    assert batch.json()["total_amount"] == 700
    assert batch.json()["stores"][0]["store_id"] == 3
