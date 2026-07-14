from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import database, models
from app.routers import checkout as checkout_router
from app.utils import utc_now

DEMO_USER_ID = 100
STORE_ID = 3  # 우리분식: discount_rate 10%(max 2,000원) + discount_amount 1,000원(min 5,000원) 보유
HEADERS = {"X-User-Id": str(DEMO_USER_ID)}


@pytest.fixture(autouse=True)
def mock_toss_confirm(monkeypatch):
    def confirm_payment(payment_key: str, order_id: str, amount: int):
        return {
            "paymentKey": payment_key,
            "orderId": order_id,
            "totalAmount": amount,
            "status": "DONE",
            "method": "간편결제",
        }

    monkeypatch.setattr(checkout_router, "confirm_toss_payment", confirm_payment)


def _claim_store_coupons(client: TestClient) -> None:
    coupons = client.get("/coupons", headers=HEADERS).json()["coupons"]
    store_coupon_ids = [c["id"] for c in coupons if c["store_name"] == "우리분식"]
    assert len(store_coupon_ids) == 2
    for coupon_id in store_coupon_ids:
        res = client.post(f"/coupons/{coupon_id}/claim", headers=HEADERS)
        assert res.status_code == 201


def _benefit_by_kind(benefits: list[dict], kind: str) -> dict:
    matches = [b for b in benefits if b["kind"] == kind]
    assert len(matches) == 1, f"{kind} benefit not found in {benefits}"
    return matches[0]


def test_checkout_benefits_small_amount_below_min_payment(client: TestClient):
    _claim_store_coupons(client)

    res = client.get("/checkout/benefits", params={"store_id": STORE_ID, "amount": 4000}, headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["store_name"] == "우리분식"
    assert body["amount"] == 4000

    rate = _benefit_by_kind(body["benefits"], "coupon_rate")
    assert rate["discount"] == 400
    assert rate["selectable"] is True
    assert rate["reason"] is None

    flat = _benefit_by_kind(body["benefits"], "coupon_amount")
    assert flat["discount"] == 0
    assert flat["selectable"] is False
    assert flat["reason"] == "5,000원 이상부터 사용 가능"

    none_benefit = _benefit_by_kind(body["benefits"], "none")
    assert none_benefit["selectable"] is True


def test_checkout_benefits_mid_amount_matches_spec_example(client: TestClient):
    _claim_store_coupons(client)

    res = client.get("/checkout/benefits", params={"store_id": STORE_ID, "amount": 18000}, headers=HEADERS)
    assert res.status_code == 200
    body = res.json()

    rate = _benefit_by_kind(body["benefits"], "coupon_rate")
    assert rate["discount"] == 1800
    assert rate["selectable"] is True
    assert rate["reason"] is None

    flat = _benefit_by_kind(body["benefits"], "coupon_amount")
    assert flat["discount"] == 1000
    assert flat["selectable"] is True
    assert flat["reason"] is None


def test_checkout_benefits_large_amount_hits_max_discount_cap(client: TestClient):
    _claim_store_coupons(client)

    res = client.get("/checkout/benefits", params={"store_id": STORE_ID, "amount": 30000}, headers=HEADERS)
    assert res.status_code == 200
    body = res.json()

    rate = _benefit_by_kind(body["benefits"], "coupon_rate")
    # 10% * 30000 = 3000원이지만 max_discount=2000원 상한에 걸린다
    assert rate["discount"] == 2000
    assert rate["selectable"] is True
    assert rate["reason"] == "최대 2,000원 적용"

    flat = _benefit_by_kind(body["benefits"], "coupon_amount")
    assert flat["discount"] == 1000
    assert flat["selectable"] is True
    assert flat["reason"] is None


def test_checkout_success_consumes_coupon_and_logs_transaction(client: TestClient):
    _claim_store_coupons(client)

    benefits = client.get(
        "/checkout/benefits", params={"store_id": STORE_ID, "amount": 18000}, headers=HEADERS
    ).json()["benefits"]
    rate_benefit_id = _benefit_by_kind(benefits, "coupon_rate")["benefit_id"]

    res = client.post(
        "/checkout",
        json={
            "store_id": STORE_ID,
            "amount": 18000,
            "benefit_id": rate_benefit_id,
            "method": "easy_pay",
            "paymentKey": "test-payment-key-1",
            "orderId": "checkout-order-1",
            "payment_amount": 16200,
        },
        headers=HEADERS,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["result"] == "success"
    assert body["final_amount"] == 18000 - 1800
    assert body["benefit_kind"] == "coupon_rate"
    assert body["consumed"] is True

    # 쿠폰이 소진돼서 같은 쿠폰으로 다시 결제를 시도하면 실패한다
    res2 = client.post(
        "/checkout",
        json={
            "store_id": STORE_ID,
            "amount": 18000,
            "benefit_id": rate_benefit_id,
            "method": "easy_pay",
            "paymentKey": "test-payment-key-2",
            "orderId": "checkout-order-2",
            "payment_amount": 16200,
        },
        headers=HEADERS,
    )
    assert res2.status_code == 200
    assert res2.json()["result"] == "fail"

    transactions = client.get("/me/transactions", headers=HEADERS).json()["transactions"]
    assert any(t["type"] == "coupon_use" and t["amount"] == -1800 for t in transactions)


def test_checkout_rejects_tampered_payment_amount_before_confirm(client: TestClient, monkeypatch):
    called = False

    def should_not_be_called(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(checkout_router, "confirm_toss_payment", should_not_be_called)
    res = client.post(
        "/checkout",
        json={
            "store_id": STORE_ID,
            "amount": 18000,
            "benefit_id": "none",
            "method": "card",
            "paymentKey": "tampered-payment-key",
            "orderId": "tampered-order-1",
            "payment_amount": 100,
        },
        headers=HEADERS,
    )

    assert res.status_code == 400
    assert res.json()["error"] == "payment_amount_mismatch"
    assert called is False


def test_checkout_same_confirmation_is_idempotent(client: TestClient):
    payload = {
        "store_id": STORE_ID,
        "amount": 18000,
        "benefit_id": "none",
        "method": "card",
        "paymentKey": "idempotent-payment-key",
        "orderId": "idempotent-order-1",
        "payment_amount": 18000,
    }
    first = client.post("/checkout", json=payload, headers=HEADERS)
    second = client.post("/checkout", json=payload, headers=HEADERS)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()


def test_checkout_requires_toss_info_when_final_amount_is_positive(client: TestClient, monkeypatch):
    called = False

    def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(checkout_router, "confirm_toss_payment", should_not_be_called)
    res = client.post(
        "/checkout",
        json={
            "store_id": STORE_ID,
            "amount": 18000,
            "benefit_id": "none",
            "method": "card",
        },
        headers=HEADERS,
    )

    assert res.status_code == 400
    assert res.json()["error"] == "payment_info_required"
    assert called is False


def test_checkout_confirmation_failure_rolls_back_benefit_changes(client: TestClient, monkeypatch):
    _claim_store_coupons(client)
    benefits = client.get(
        "/checkout/benefits", params={"store_id": STORE_ID, "amount": 18000}, headers=HEADERS
    ).json()["benefits"]
    benefit_id = _benefit_by_kind(benefits, "coupon_rate")["benefit_id"]
    user_coupon_id = int(benefit_id.split(":", 1)[1])

    def fail_confirm(*args, **kwargs):
        raise HTTPException(
            status_code=400,
            detail={"error": "payment_confirm_failed", "message": "결제 승인이 거절됐어요"},
        )

    monkeypatch.setattr(checkout_router, "confirm_toss_payment", fail_confirm)
    res = client.post(
        "/checkout",
        json={
            "store_id": STORE_ID,
            "amount": 18000,
            "benefit_id": benefit_id,
            "method": "card",
            "paymentKey": "failed-checkout-key",
            "orderId": "failed-checkout-order",
            "payment_amount": 16200,
        },
        headers=HEADERS,
    )

    assert res.status_code == 400
    assert res.json()["error"] == "payment_confirm_failed"
    db = database.SessionLocal()
    try:
        assert db.get(models.UserCoupon, user_coupon_id).status == "active"
        assert db.query(models.Transaction).filter(models.Transaction.type == "coupon_use").count() == 0
        assert db.query(models.Payment).count() == 0
        assert db.query(models.TossPayment).count() == 0
    finally:
        db.close()


def test_checkout_full_discount_skips_toss_and_commits_locally(client: TestClient, monkeypatch):
    db = database.SessionLocal()
    try:
        coupon = models.Coupon(
            store_id=STORE_ID,
            type="discount_amount",
            title="전액 할인",
            value=5000,
            target="전 메뉴",
            valid_until=utc_now() + timedelta(days=1),
            time_limit_hours=None,
            store_only=True,
            min_payment=0,
            max_discount=None,
        )
        db.add(coupon)
        db.flush()
        user_coupon = models.UserCoupon(
            user_id=DEMO_USER_ID,
            coupon_id=coupon.id,
            status="active",
            claimed_at=utc_now(),
        )
        db.add(user_coupon)
        db.commit()
        user_coupon_id = user_coupon.id
    finally:
        db.close()

    called = False

    def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(checkout_router, "confirm_toss_payment", should_not_be_called)
    res = client.post(
        "/checkout",
        json={
            "store_id": STORE_ID,
            "amount": 5000,
            "benefit_id": f"coupon:{user_coupon_id}",
            "method": "card",
        },
        headers=HEADERS,
    )

    assert res.status_code == 200
    assert res.json()["final_amount"] == 0
    assert res.json()["payment_status"] == "NOT_REQUIRED"
    assert called is False

    db = database.SessionLocal()
    try:
        assert db.get(models.UserCoupon, user_coupon_id).status == "used"
        assert db.query(models.Payment).filter(models.Payment.amount == 0).count() == 1
        assert db.query(models.TossPayment).count() == 0
        assert db.query(models.Transaction).filter(models.Transaction.type == "coupon_use").count() == 1
    finally:
        db.close()


def test_checkout_benefits_requires_user(client: TestClient):
    res = client.get("/checkout/benefits", params={"store_id": STORE_ID, "amount": 10000})
    assert res.status_code == 401
