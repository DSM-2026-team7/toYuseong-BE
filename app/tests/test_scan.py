from fastapi.testclient import TestClient

OWNER_AUTH = {"Authorization": "Bearer 1"}  # store_id=1 (동네커피 유성점) owner
CUSTOMER_HEADERS = {"X-User-Id": "100"}


def test_scan_stamp_qr_awards_stamp_and_is_single_use(client: TestClient):
    created = client.post("/admin/qrs/stamp", headers=OWNER_AUTH, json={})
    assert created.status_code == 201
    body = created.json()
    assert body["type"] == "stamp"
    assert body["amount"] is None
    token = body["token"]

    res = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": token})
    assert res.status_code == 200
    result = res.json()
    assert result["kind"] == "stamp"
    assert result["store_name"] == "동네커피 유성점"
    assert result["current"] == 1
    assert result["goal"] == 5
    assert result["card_created"] is True
    assert result["reward_reached"] is False

    # 1회용이라 같은 토큰으로 다시 스캔하면 409
    res2 = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": token})
    assert res2.status_code == 409
    assert res2.json() == {"error": "already_used", "message": "이미 처리된 QR이에요"}


def test_scan_stamp_qr_can_carry_display_amount(client: TestClient):
    created = client.post("/admin/qrs/stamp", headers=OWNER_AUTH, json={"amount": 4500})
    token = created.json()["token"]

    res = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": token})
    assert res.status_code == 200
    assert res.json()["amount"] == 4500
    assert res.json()["kind"] == "stamp"


def test_scan_payment_qr_returns_checkout_ready(client: TestClient):
    created = client.post("/admin/qrs/direct", headers=OWNER_AUTH, json={"amount": 18000})
    assert created.status_code == 201
    token = created.json()["token"]
    assert created.json()["type"] == "payment"

    res = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": token})
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "kind": "payment",
        "store_id": 1,
        "store_name": "동네커피 유성점",
        "amount": 18000,
        "checkout_ready": True,
    }

    res2 = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": token})
    assert res2.status_code == 409


def test_scan_invalid_token_returns_400(client: TestClient):
    res = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": "does-not-exist"})
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_qr", "message": "유효하지 않은 QR이에요"}


def test_scan_requires_customer_auth(client: TestClient):
    res = client.post("/scan", json={"qr_token": "whatever"})
    assert res.status_code == 401


def test_scan_stamp_failure_leaves_qr_reusable(client: TestClient):
    """오늘 이미 적립했으면 409가 나지만, QR 자체는 소진되지 않아야 다음날 재사용 가능."""
    created = client.post("/admin/qrs/stamp", headers=OWNER_AUTH, json={})
    token = created.json()["token"]

    first = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": token})
    assert first.status_code == 200

    created2 = client.post("/admin/qrs/stamp", headers=OWNER_AUTH, json={})
    token2 = created2.json()["token"]
    second = client.post("/scan", headers=CUSTOMER_HEADERS, json={"qr_token": token2})
    assert second.status_code == 409
    assert second.json()["error"] == "already_stamped_today"

    # QR은 already_stamped_today로 실패했을 뿐이니 WAITING 그대로 남아있어야 한다
    qr_status = client.get(f"/admin/qrs/{created2.json()['qrId']}", headers=OWNER_AUTH)
    assert qr_status.json()["status"] == "WAITING"
