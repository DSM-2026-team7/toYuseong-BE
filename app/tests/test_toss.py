import base64

import httpx
import pytest
from fastapi import HTTPException

from app import toss


def test_confirm_toss_payment_sends_expected_request(monkeypatch):
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return httpx.Response(
            200,
            json={
                "paymentKey": json["paymentKey"],
                "orderId": json["orderId"],
                "totalAmount": json["amount"],
                "status": "DONE",
            },
        )

    monkeypatch.setattr(toss.httpx, "post", fake_post)
    result = toss.confirm_toss_payment("payment-key", "order-id", 9900)

    encoded = base64.b64encode(f"{toss.TOSS_SECRET_KEY}:".encode("utf-8")).decode("utf-8")
    assert captured == {
        "url": "https://api.tosspayments.com/v1/payments/confirm",
        "json": {"paymentKey": "payment-key", "orderId": "order-id", "amount": 9900},
        "headers": {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        },
        "timeout": 10.0,
    }
    assert result["status"] == "DONE"


def test_confirm_toss_payment_forwards_toss_error(monkeypatch):
    monkeypatch.setattr(
        toss.httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            400,
            json={"code": "INVALID_REQUEST", "message": "잘못된 결제 정보예요"},
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        toss.confirm_toss_payment("payment-key", "order-id", 9900)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "error": "INVALID_REQUEST",
        "message": "잘못된 결제 정보예요",
    }


def test_confirm_toss_payment_converts_network_error(monkeypatch):
    request = httpx.Request("POST", "https://api.tosspayments.com/v1/payments/confirm")

    def fail_post(*args, **kwargs):
        raise httpx.ConnectError("connection failed", request=request)

    monkeypatch.setattr(toss.httpx, "post", fail_post)

    with pytest.raises(HTTPException) as exc_info:
        toss.confirm_toss_payment("payment-key", "order-id", 9900)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["error"] == "toss_network_error"
