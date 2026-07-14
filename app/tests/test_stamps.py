import base64
import json
from datetime import timedelta

from fastapi.testclient import TestClient

from app import database, models
from app.utils import utc_now

DEMO_USER_ID = 100
DEMO_STORE_ID = 1
DEMO_STORE_NAME = "동네커피 유성점"
DEMO_REWARD = "아메리카노 1잔 무료"


def make_token(user_id: int) -> str:
    raw = json.dumps({"user": user_id}).encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


def backdate_card(days: int) -> None:
    db = database.SessionLocal()
    try:
        card = (
            db.query(models.StampCard)
            .filter(models.StampCard.user_id == DEMO_USER_ID, models.StampCard.store_id == DEMO_STORE_ID)
            .first()
        )
        assert card is not None
        card.updated_at = utc_now() - timedelta(days=days)
        latest_earn = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.user_id == DEMO_USER_ID,
                models.Transaction.type == "stamp_earn",
            )
            .order_by(models.Transaction.created_at.desc())
            .first()
        )
        assert latest_earn is not None
        latest_earn.created_at = utc_now() - timedelta(days=days)
        db.commit()
    finally:
        db.close()


def test_stamp_loop_first_earn_then_duplicate_then_reward(client: TestClient):
    token = make_token(DEMO_USER_ID)

    # 1) 첫 적립 -> 카드 자동 생성
    res = client.post(
        "/stamps",
        json={"store_id": DEMO_STORE_ID, "customer_token": token, "amount": 4500},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["store_name"] == DEMO_STORE_NAME
    assert body["current"] == 1
    assert body["goal"] == 5
    assert body["card_created"] is True
    assert body["reward_reached"] is False
    assert body["reward"] is None

    # 2) 같은 날 재적립 -> 409
    res = client.post("/stamps", json={"store_id": DEMO_STORE_ID, "customer_token": token})
    assert res.status_code == 409
    body = res.json()
    assert body == {"error": "already_stamped_today", "message": "오늘은 이미 적립했어요"}

    # 3) 날짜를 넘겨가며 3번 더 적립 (2/5 -> 4/5)
    for _ in range(3):
        backdate_card(days=1)
        res = client.post("/stamps", json={"store_id": DEMO_STORE_ID, "customer_token": token})
        assert res.status_code == 200
        assert res.json()["reward_reached"] is False

    # 4) 5번째 적립 -> 리워드 쿠폰 발급 + 카드 리셋
    backdate_card(days=1)
    res = client.post("/stamps", json={"store_id": DEMO_STORE_ID, "customer_token": token})
    assert res.status_code == 200
    body = res.json()
    assert body["current"] == 5
    assert body["goal"] == 5
    assert body["reward_reached"] is True
    assert body["reward"] == DEMO_REWARD
    assert body["card_created"] is False
    assert body["card_reset_to"] == 0
    assert body["reward_coupon"]["title"] == f"{DEMO_REWARD} 쿠폰"
    assert body["reward_coupon"]["d_day"] == 30
    assert isinstance(body["reward_coupon"]["user_coupon_id"], int)

    # DB 상의 카드도 실제로 0으로 리셋되었는지 확인
    db = database.SessionLocal()
    try:
        card = (
            db.query(models.StampCard)
            .filter(models.StampCard.user_id == DEMO_USER_ID, models.StampCard.store_id == DEMO_STORE_ID)
            .first()
        )
        assert card.current == 0

        user_coupon = (
            db.query(models.UserCoupon)
            .filter(models.UserCoupon.id == body["reward_coupon"]["user_coupon_id"])
            .first()
        )
        assert user_coupon is not None
        assert user_coupon.status == "active"
        assert user_coupon.user_id == DEMO_USER_ID
    finally:
        db.close()


def test_invalid_store_id_returns_400(client: TestClient):
    token = make_token(DEMO_USER_ID)
    res = client.post("/stamps", json={"store_id": 9999, "customer_token": token})
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_qr", "message": "유효하지 않은 QR이에요"}


def test_invalid_customer_token_returns_400(client: TestClient):
    res = client.post(
        "/stamps",
        json={"store_id": DEMO_STORE_ID, "customer_token": "not-a-valid-token"},
    )
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_qr", "message": "유효하지 않은 QR이에요"}
