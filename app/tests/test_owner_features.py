from datetime import datetime, timedelta, timezone

from app import database, models
from app.routers import checkout as checkout_router
from app.utils import utc_now
from web.auth import create_token


OWNER_1 = {"Authorization": "Bearer 1"}
CUSTOMER = {"X-User-Id": "100"}


def _operator_headers() -> dict[str, str]:
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


def test_owner_registration_approval_and_reverification(client):
    db = database.SessionLocal()
    try:
        db.add(
            models.User(
                id=999,
                nickname="신규 사장님",
                region="유성구",
                role="owner",
                owner_enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()
    owner = {"Authorization": "Bearer owner-999"}

    registered = client.post(
        "/admin/register",
        headers=owner,
        json={
            "name": "신규 카페",
            "register_num": "111-22-33333",
            "category": "cafe",
            "address": "대전 유성구 궁동 123",
            "phone_no": "042-111-2222",
            "business_hours": "09:00-20:00",
        },
    )
    assert registered.status_code == 201
    application_id = registered.json()["application_id"]
    assert registered.json()["status"] == "pending"
    assert client.get("/admin/verification", headers=owner).json()["status"] == "pending"
    blocked = client.get("/admin/menus", headers=owner)
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "store_verification_pending"

    approved = client.post(
        f"/admin/applications/{application_id}/approve",
        headers=_operator_headers(),
    )
    assert approved.status_code == 200
    assert client.get("/admin/verification", headers=owner).json()["status"] == "approved"
    shop = client.get("/admin/shop", headers=owner)
    assert shop.status_code == 200
    assert shop.json()["name"] == "신규 카페"
    assert shop.json()["region"] == "유성구 궁동"
    assert shop.json()["address"] == "대전 유성구 궁동 123"
    assert client.get("/admin/stamp-policy", headers=owner).json()["configured"] is False

    changed = client.patch(
        "/admin/shop",
        headers=owner,
        json={"name": "수정 카페", "address": "대전 유성구 봉명동 10"},
    )
    assert changed.status_code == 202
    assert changed.json()["status"] == "pending"
    assert client.get("/admin/owner/dashboard", headers=owner).status_code == 403

    reapplied_id = changed.json()["application_id"]
    assert client.post(
        f"/admin/applications/{reapplied_id}/approve",
        headers=_operator_headers(),
    ).status_code == 200
    updated = client.get("/admin/shop", headers=owner).json()
    assert updated["name"] == "수정 카페"
    assert updated["region"] == "유성구 봉명동"


def test_owner_coupon_stop_keeps_claimed_coupon_usable_and_updates_dashboard(client):
    created = client.post(
        "/admin/coupons",
        headers=OWNER_1,
        json={
            "type": "fixed",
            "coupon_name": "한정 1천원 할인",
            "sale_price": 1000,
            "min_buy_price": 5000,
            "coupon_num": 2,
            "is_coupon_infinity": False,
        },
    )
    assert created.status_code == 201
    coupon_id = created.json()["id"]
    assert created.json()["expiry_date"] is None

    claimed = client.post(f"/coupons/{coupon_id}/claim", headers=CUSTOMER)
    assert claimed.status_code == 201
    stopped = client.post(f"/admin/coupons/{coupon_id}/stop", headers=OWNER_1)
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"

    public_ids = {item["id"] for item in client.get("/coupons").json()["coupons"]}
    assert coupon_id not in public_ids

    db = database.SessionLocal()
    try:
        db.add(models.User(id=101, nickname="두번째 손님", region="유성구", role="customer"))
        db.add(
            models.Transaction(
                user_id=100,
                type="pass_use",
                store_name="동네커피 유성점",
                amount=-500,
                memo="정산 테스트",
                created_at=utc_now(),
            )
        )
        db.commit()
    finally:
        db.close()

    new_claim = client.post(f"/coupons/{coupon_id}/claim", headers={"X-User-Id": "101"})
    assert new_claim.status_code == 410
    assert new_claim.json()["error"] == "coupon_issuance_stopped"

    # 발급 중단 전에 받은 쿠폰은 계속 사용할 수 있다.
    used = client.post(
        f"/me/coupons/{claimed.json()['user_coupon_id']}/use",
        headers=CUSTOMER,
    )
    assert used.status_code == 200

    dashboard = client.get("/admin/owner/dashboard", headers=OWNER_1)
    assert dashboard.status_code == 200
    assert dashboard.json()["settlement_expected"] == 500
    assert dashboard.json()["coupon_issued"] == 1
    assert dashboard.json()["coupon_used"] == 1
    assert dashboard.json()["stopped_coupon_count"] == 1


def _backdate_latest_stamp() -> None:
    db = database.SessionLocal()
    try:
        transaction = (
            db.query(models.Transaction)
            .filter(models.Transaction.user_id == 100, models.Transaction.type == "stamp_earn")
            .order_by(models.Transaction.created_at.desc())
            .first()
        )
        transaction.created_at = utc_now() - timedelta(days=2)
        db.commit()
    finally:
        db.close()


def test_stamp_setting_minimum_menu_qr_and_completion_limit(client):
    configured = client.put(
        "/admin/stamp-policy",
        headers=OWNER_1,
        json={
            "goal": 2,
            "min_amount": 5000,
            "completion_limit": 1,
            "reward_name": "10% 리워드",
            "reward_type": "discount_rate",
            "reward_value": 10,
            "reward_min_payment": 5000,
            "reward_max_discount": 1000,
            "reward_valid_days": 7,
            "active": True,
        },
    )
    assert configured.status_code == 200
    assert configured.json()["min_amount"] == 5000

    too_small = client.post("/admin/qrs/stamp", headers=OWNER_1, json={"amount": 4000})
    assert too_small.status_code == 400
    assert too_small.json()["error"] == "stamp_minimum_not_met"

    first_menu = client.post("/admin/menus", headers=OWNER_1, json={"name": "커피", "price": 3000})
    second_menu = client.post("/admin/menus", headers=OWNER_1, json={"name": "케이크", "price": 2500})
    qr = client.post(
        "/admin/qrs/stamp",
        headers=OWNER_1,
        json={"menuIds": [first_menu.json()["menuId"], second_menu.json()["menuId"]]},
    )
    assert qr.status_code == 201
    assert qr.json()["amount"] == 5500
    expires_at = datetime.fromisoformat(qr.json()["expiresAt"].replace("Z", "+00:00"))
    assert timedelta(minutes=4, seconds=50) <= expires_at - datetime.now(timezone.utc) <= timedelta(minutes=5, seconds=5)

    assert client.post("/scan", headers=CUSTOMER, json={"qr_token": qr.json()["token"]}).status_code == 200
    _backdate_latest_stamp()
    second_qr = client.post("/admin/qrs/stamp", headers=OWNER_1, json={"amount": 6000})
    completed = client.post("/scan", headers=CUSTOMER, json={"qr_token": second_qr.json()["token"]})
    assert completed.status_code == 200
    assert completed.json()["reward_reached"] is True

    db = database.SessionLocal()
    try:
        reward = db.get(models.UserCoupon, completed.json()["reward_coupon"]["user_coupon_id"])
        coupon = db.get(models.Coupon, reward.coupon_id)
        card = db.query(models.StampCard).filter(models.StampCard.user_id == 100, models.StampCard.store_id == 1).one()
        assert coupon.type == "discount_rate"
        assert coupon.value == 10
        assert coupon.max_discount == 1000
        assert coupon.source == "stamp_reward"
        assert card.completed_count == 1
        reward_coupon_id = coupon.id
    finally:
        db.close()

    assert reward_coupon_id not in {
        item["id"] for item in client.get("/coupons").json()["coupons"]
    }

    _backdate_latest_stamp()
    third_qr = client.post("/admin/qrs/stamp", headers=OWNER_1, json={"amount": 6000})
    limited = client.post("/scan", headers=CUSTOMER, json={"qr_token": third_qr.json()["token"]})
    assert limited.status_code == 409
    assert limited.json()["error"] == "stamp_completion_limit_reached"


def test_owner_can_poll_completed_payment_with_benefit_and_threshold(client, monkeypatch):
    monkeypatch.setattr(checkout_router, "confirm_toss_payment", _confirmed)
    client.put(
        "/admin/stamp-policy",
        headers=OWNER_1,
        json={
            "goal": 5,
            "min_amount": 20000,
            "completion_limit": None,
            "reward_name": "1천원 리워드",
            "reward_type": "discount_amount",
            "reward_value": 1000,
            "reward_min_payment": 0,
            "reward_max_discount": None,
            "reward_valid_days": 30,
            "active": True,
        },
    )
    coupon = client.post(
        "/admin/coupons",
        headers=OWNER_1,
        json={
            "type": "fixed",
            "coupon_name": "결제 테스트 쿠폰",
            "sale_price": 1000,
            "min_buy_price": 0,
            "is_coupon_infinity": True,
        },
    )
    claimed = client.post(f"/coupons/{coupon.json()['id']}/claim", headers=CUSTOMER)
    qr = client.post("/admin/qrs/direct", headers=OWNER_1, json={"amount": 18000})
    assert client.post("/scan", headers=CUSTOMER, json={"qr_token": qr.json()["token"]}).status_code == 200

    paid = client.post(
        "/checkout",
        headers=CUSTOMER,
        json={
            "store_id": 1,
            "amount": 18000,
            "benefit_id": f"coupon:{claimed.json()['user_coupon_id']}",
            "method": "card",
            "paymentKey": "owner-result-payment-key",
            "orderId": "owner-result-order-id",
            "payment_amount": 17000,
            "qr_token": qr.json()["token"],
        },
    )
    assert paid.status_code == 200
    assert paid.json()["stamp"] is None  # 기준 금액 20,000원 미달

    result = client.get(f"/admin/qrs/{qr.json()['qrId']}/result", headers=OWNER_1)
    assert result.status_code == 200
    assert result.json()["status"] == "CONSUMED"
    assert result.json()["paidAmount"] == 17000
    assert result.json()["discountAmount"] == 1000
    assert "결제 테스트 쿠폰" in result.json()["benefitSummary"]
