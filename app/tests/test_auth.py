from fastapi.testclient import TestClient


def test_list_accounts_includes_customer_and_owners(client: TestClient):
    res = client.get("/auth/accounts")
    assert res.status_code == 200
    accounts = res.json()["accounts"]

    customer_accounts = [a for a in accounts if a["role"] == "customer"]
    owner_accounts = [a for a in accounts if a["role"] == "owner"]

    assert any(a["user_id"] == 100 and a["nickname"] == "홍길동" for a in customer_accounts)
    assert len(owner_accounts) == 6
    owner1 = next(a for a in owner_accounts if a["user_id"] == 1)
    assert owner1["store_id"] == 1
    assert owner1["store_name"] == "동네커피 유성점"


def test_login_as_customer_returns_user_id_for_x_user_id_header(client: TestClient):
    res = client.post("/auth/login", json={"role": "customer", "user_id": 100})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "customer"
    assert body["user_id"] == 100
    assert body["nickname"] == "홍길동"
    assert body["region"] == "유성구 온천2동"
    assert body["store_id"] is None
    assert body["token"] is None

    # 응답의 user_id를 X-User-Id로 그대로 써서 고객 API가 되는지 확인
    me = client.get("/me", headers={"X-User-Id": str(body["user_id"])})
    assert me.status_code == 200
    assert me.json()["nickname"] == "홍길동"


def test_login_as_owner_returns_token_for_admin_api(client: TestClient):
    res = client.post("/auth/login", json={"role": "owner", "user_id": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "owner"
    assert body["user_id"] == 1
    assert body["store_id"] == 1
    assert body["store_name"] == "동네커피 유성점"
    assert body["token"] == "1"

    # 응답의 token을 Authorization: Bearer로 그대로 써서 사장님 API가 되는지 확인
    shop = client.get("/admin/shop", headers={"Authorization": f"Bearer {body['token']}"})
    assert shop.status_code == 200
    assert shop.json()["name"] == "동네커피 유성점"


def test_login_role_mismatch_returns_403(client: TestClient):
    res = client.post("/auth/login", json={"role": "owner", "user_id": 100})
    assert res.status_code == 403
    assert res.json() == {"error": "role_mismatch", "message": "사장님 계정이 아니에요"}

    res2 = client.post("/auth/login", json={"role": "customer", "user_id": 1})
    assert res2.status_code == 403
    assert res2.json() == {"error": "role_mismatch", "message": "사용자 계정이 아니에요"}


def test_login_unknown_user_returns_404(client: TestClient):
    res = client.post("/auth/login", json={"role": "customer", "user_id": 999999})
    assert res.status_code == 404
    assert res.json() == {"error": "user_not_found", "message": "계정을 찾을 수 없어요"}
