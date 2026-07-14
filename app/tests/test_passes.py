from datetime import timedelta

from fastapi import HTTPException

from app import database, models
from app.routers import passes as passes_router
from app.utils import utc_now


HEADERS = {"X-User-Id": "100"}


def test_expired_pass_is_not_reported_as_owned(client):
    db = database.SessionLocal()
    try:
        db.add(models.UserPass(
            user_id=100,
            pass_id=1,
            status="active",
            purchased_at=utc_now() - timedelta(days=2),
            expires_at=utc_now() - timedelta(days=1),
        ))
        db.commit()
    finally:
        db.close()

    passes = client.get("/passes", headers=HEADERS).json()["passes"]
    assert next(item for item in passes if item["id"] == 1)["owned"] is False
    assert client.get("/passes/1", headers=HEADERS).json()["owned"] is False


def test_pass_is_issued_only_after_toss_confirmation(client, monkeypatch):
    calls = []

    def confirm_payment(payment_key: str, order_id: str, amount: int):
        calls.append((payment_key, order_id, amount))
        return {
            "paymentKey": payment_key,
            "orderId": order_id,
            "totalAmount": amount,
            "status": "DONE",
            "method": "카드",
        }

    monkeypatch.setattr(passes_router, "confirm_toss_payment", confirm_payment)
    payload = {
        "duration_days": 30,
        "paymentKey": "pass-payment-key-1",
        "orderId": "pass-order-1",
        "amount": 9900,
    }
    first = client.post("/passes/2/purchase", json=payload, headers=HEADERS)
    second = client.post("/passes/2/purchase", json=payload, headers=HEADERS)

    assert first.status_code == 201
    assert first.json()["paid"] == 9900
    assert first.json()["payment_status"] == "DONE"
    assert second.json() == first.json()
    assert calls == [("pass-payment-key-1", "pass-order-1", 9900)]

    db = database.SessionLocal()
    try:
        assert db.query(models.UserPass).filter(models.UserPass.pass_id == 2).count() == 1
        assert db.query(models.TossPayment).filter(models.TossPayment.order_id == "pass-order-1").count() == 1
    finally:
        db.close()


def test_pass_price_mismatch_does_not_call_toss(client, monkeypatch):
    called = False

    def should_not_be_called(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(passes_router, "confirm_toss_payment", should_not_be_called)
    res = client.post(
        "/passes/2/purchase",
        json={
            "duration_days": 30,
            "paymentKey": "pass-payment-key-2",
            "orderId": "pass-order-2",
            "amount": 100,
        },
        headers=HEADERS,
    )

    assert res.status_code == 400
    assert res.json()["error"] == "payment_amount_mismatch"
    assert called is False


def test_pass_is_not_issued_when_toss_confirmation_fails(client, monkeypatch):
    def fail_confirm(*args, **kwargs):
        raise HTTPException(
            status_code=400,
            detail={"error": "payment_confirm_failed", "message": "결제 승인이 거절됐어요"},
        )

    monkeypatch.setattr(passes_router, "confirm_toss_payment", fail_confirm)
    res = client.post(
        "/passes/2/purchase",
        json={
            "duration_days": 30,
            "paymentKey": "pass-payment-key-3",
            "orderId": "pass-order-3",
            "amount": 9900,
        },
        headers=HEADERS,
    )

    assert res.status_code == 400
    assert res.json() == {"error": "payment_confirm_failed", "message": "결제 승인이 거절됐어요"}
    db = database.SessionLocal()
    try:
        assert db.query(models.UserPass).filter(models.UserPass.pass_id == 2).count() == 0
        assert db.query(models.TossPayment).count() == 0
    finally:
        db.close()
