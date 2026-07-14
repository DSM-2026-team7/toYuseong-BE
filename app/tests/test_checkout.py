from fastapi.testclient import TestClient

DEMO_USER_ID = 100
STORE_ID = 3  # 우리분식: discount_rate 10%(max 2,000원) + discount_amount 1,000원(min 5,000원) 보유
HEADERS = {"X-User-Id": str(DEMO_USER_ID)}


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
        json={"store_id": STORE_ID, "amount": 18000, "benefit_id": rate_benefit_id, "method": "easy_pay"},
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
        json={"store_id": STORE_ID, "amount": 18000, "benefit_id": rate_benefit_id, "method": "easy_pay"},
        headers=HEADERS,
    )
    assert res2.status_code == 200
    assert res2.json()["result"] == "fail"

    transactions = client.get("/me/transactions", headers=HEADERS).json()["transactions"]
    assert any(t["type"] == "coupon_use" and t["amount"] == -1800 for t in transactions)


def test_checkout_benefits_requires_user(client: TestClient):
    res = client.get("/checkout/benefits", params={"store_id": STORE_ID, "amount": 10000})
    assert res.status_code == 401
