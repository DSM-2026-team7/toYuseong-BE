"""관리자 로그인 + 인증 흐름 검증."""
from fastapi.testclient import TestClient
from app.main import app
import os

if os.path.exists("toyuseong.db"):
    try:
        os.remove("toyuseong.db")
    except PermissionError:
        pass

with TestClient(app) as client:
    # 1. 로그인 실패 (잘못된 비밀번호)
    print("=== Login Fail ===")
    r = client.post("/admin/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    print(f"  401 OK: {r.json()}")

    # 2. 로그인 성공
    print("\n=== Login Success ===")
    r = client.post("/admin/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200
    data = r.json()
    token = data["token"]
    print(f"  name: {data['name']}")
    print(f"  token: {token}")

    # 로컬에서 토큰 검증
    from web.auth import decode_token
    try:
        payload = decode_token(token)
        print(f"  local decode OK: {payload}")
    except Exception as e:
        print(f"  local decode FAIL: {e}")

    # 3. 토큰 없이 admin API 호출 → 403
    print("\n=== No Token → 403 ===")
    r = client.get("/admin/dashboard")
    assert r.status_code in (401, 403), f"Expected 401 or 403, got {r.status_code}"
    print(f"  {r.status_code} OK: unauthorized blocked")

    # 4. 토큰으로 admin API 호출 → 200
    print("\n=== With Token → 200 ===")
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/admin/dashboard", headers=headers)
    print(f"  status: {r.status_code}, body: {r.text[:200]}")
    assert r.status_code == 200
    print(f"  200 OK: dashboard accessible")

    # 5. 다른 admin API도 토큰으로 접근 가능
    print("\n=== Applications with Token ===")
    r = client.get("/admin/applications?status=pending", headers=headers)
    assert r.status_code == 200
    print(f"  200 OK: applications accessible")

    print("\n=== Passes with Token ===")
    r = client.get("/admin/passes", headers=headers)
    assert r.status_code == 200
    print(f"  200 OK: passes accessible")

    print("\n[OK] All auth tests passed!")
