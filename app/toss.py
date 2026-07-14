import base64
import os

import httpx
from fastapi import HTTPException


TOSS_SECRET_KEY = os.environ.get(
    "TOSS_SECRET_KEY",
    "test_sk_zXLkKEypNArWmo50nX3lmeaxYG5R",
)


def confirm_toss_payment(payment_key: str, order_id: str, amount: int) -> dict:
    """토스페이먼츠 승인 API를 동기식으로 호출하여 검증 및 승인합니다."""
    url = "https://api.tosspayments.com/v1/payments/confirm"
    userpass = f"{TOSS_SECRET_KEY}:"
    encoded_userpass = base64.b64encode(userpass.encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": f"Basic {encoded_userpass}",
        "Content-Type": "application/json",
    }
    payload = {
        "paymentKey": payment_key,
        "orderId": order_id,
        "amount": amount,
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        if response.status_code != 200:
            try:
                error_data = response.json()
            except ValueError:
                error_data = {}
            if not isinstance(error_data, dict):
                error_data = {}
            raise HTTPException(
                status_code=response.status_code,
                detail={
                    "error": error_data.get("code", "TOSS_PAYMENT_ERROR"),
                    "message": error_data.get(
                        "message",
                        "토스페이먼츠 결제 승인에 실패했어요",
                    ),
                },
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "invalid_toss_response",
                    "message": "토스페이먼츠 승인 응답을 확인할 수 없어요",
                },
            ) from exc
        if not isinstance(result, dict):
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "invalid_toss_response",
                    "message": "토스페이먼츠 승인 응답 형식이 올바르지 않아요",
                },
            )
        return result
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "toss_network_error",
                "message": f"토스페이먼츠 통신 에러: {exc}",
            },
        ) from exc
