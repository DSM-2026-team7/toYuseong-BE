"""관리자 로그인 + 초기 비밀번호 변경 흐름 검증."""
from fastapi.testclient import TestClient
from app.main import app
import os

if os.path.exists("toyuseong.db"):
    try:
        os.remove("toyuseong.db")
    except PermissionError:
        pass

with TestClient(app) as client:

    # 1. 초기 로그인 (임시 비밀번호)
    print("=== 1. Login with temp password ===")
    r = client.post("/admin/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200
    data = r.json()
    temp_token = data["token"]
    print(f"  must_change_password: {data['must_change_password']}")
    assert data["must_change_password"] is True

    # 2. 비밀번호 미변경 상태로 admin API 접근 시도 -> 403
    print("\n=== 2. Access admin API without changing password -> 403 ===")
    headers = {"Authorization": f"Bearer {temp_token}"}
    r = client.get("/admin/dashboard", headers=headers)
    assert r.status_code == 403
    print(f"  {r.status_code}: {r.json()}")

    # 3. 비밀번호 변경
    print("\n=== 3. Change password ===")
    r = client.post(
        "/admin/auth/change-password",
        json={"new_password": "newpass5678"},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    new_token = data["token"]
    print(f"  message: {data['message']}")

    # 4. 새 토큰으로 admin API 접근 -> 200
    print("\n=== 4. Access admin API with new token -> 200 ===")
    headers = {"Authorization": f"Bearer {new_token}"}
    r = client.get("/admin/dashboard", headers=headers)
    assert r.status_code == 200
    print(f"  200 OK: dashboard accessible")

    # 5. 변경된 비밀번호로 재로그인
    print("\n=== 5. Re-login with new password ===")
    r = client.post("/admin/auth/login", json={"username": "admin", "password": "newpass5678"})
    assert r.status_code == 200
    data = r.json()
    print(f"  must_change_password: {data['must_change_password']}")
    assert data["must_change_password"] is False

    # 6. 재로그인 토큰으로 바로 admin API 접근 가능
    print("\n=== 6. Direct access after re-login -> 200 ===")
    headers = {"Authorization": f"Bearer {data['token']}"}
    r = client.get("/admin/passes", headers=headers)
    assert r.status_code == 200
    print(f"  200 OK: passes accessible")

    # 7. 이전 임시 비밀번호로 로그인 실패
    print("\n=== 7. Old password rejected ===")
    r = client.post("/admin/auth/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 401
    print(f"  401 OK: old password blocked")

    print("\n[OK] All password change flow tests passed!")
