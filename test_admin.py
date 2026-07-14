"""서버 기동 없이 admin API를 검증하는 스크립트."""
from fastapi.testclient import TestClient
from app.main import app
from app import models, database
from datetime import datetime, timedelta
import os

# 테스트용 DB가 있으면 초기화하여 매번 새 시드로 검증
if os.path.exists("toyuseong.db"):
    try:
        os.remove("toyuseong.db")
    except PermissionError:
        pass

with TestClient(app) as client:
    # --- 테스트 시작 직전, DB 세션을 얻어서 임시 테스트 데이터 직접 삽입 ---
    db = database.SessionLocal()
    now = datetime.utcnow()

    # 가맹점 신청: 대기 5건
    pending_apps = [
        models.StoreApplication(
            name="노른 손칼국수", category="분식·김치전", region="유성구 노은동",
            business_number="214-88-01234", business_hours="09:00 - 21:00",
            phone="042-123-4567", applicant_name="노전b", status="pending",
            applied_at=now - timedelta(hours=2),
        ),
        models.StoreApplication(
            name="온천 떡집", category="떡집·방앗", region="유성구 온천2동",
            business_number="305-22-56789", business_hours="08:00 - 20:00",
            phone="042-234-5678", applicant_name="온천2b", status="pending",
            applied_at=now - timedelta(days=1),
        ),
        models.StoreApplication(
            name="여은 문구", category="문구·팬시", region="유성구 여은동",
            business_number="412-33-67890", business_hours="10:00 - 19:00",
            phone="042-345-6789", applicant_name="여은b", status="pending",
            applied_at=now - timedelta(days=1, hours=5),
        ),
        models.StoreApplication(
            name="유성 베이커리&카페", category="카페·디저트", region="유성구 자족5동",
            business_number="501-44-78901", business_hours="07:00 - 22:00",
            phone="042-456-7890", applicant_name="자족5b", status="pending",
            applied_at=now - timedelta(days=2),
        ),
        models.StoreApplication(
            name="구현 레디오소", category="핸드·세계식", region="유성구 구현동",
            business_number="602-55-89012", business_hours="11:00 - 21:00",
            phone="042-567-8901", applicant_name="구현b", status="pending",
            applied_at=now - timedelta(days=2, hours=3),
        ),
    ]
    db.add_all(pending_apps)

    # 반려 2건
    rejected_apps = [
        models.StoreApplication(
            name="무허가 포장마차", category="음식점", region="유성구 봉명동",
            business_number="000-00-00000", business_hours="18:00 - 02:00",
            phone="010-0000-0000", applicant_name="봉명b", status="rejected",
            reject_reason="사업자등록증 확인 결과와 신청 내용이 일치하지 않아요.",
            applied_at=now - timedelta(days=5), reviewed_at=now - timedelta(days=3),
        ),
        models.StoreApplication(
            name="테스트 매장", category="기타", region="유성구 원내동",
            business_number="111-11-11111", business_hours="00:00 - 00:00",
            phone="010-1111-1111", applicant_name="원내b", status="rejected",
            reject_reason="영업시간 등 필수 정보가 누락되어 있어요. 수정 후 재신청 바랍니다.",
            applied_at=now - timedelta(days=7), reviewed_at=now - timedelta(days=5),
        ),
    ]
    db.add_all(rejected_apps)

    # 정산 데모용 유저 및 pass_use 트랜잭션
    demo_users_for_txn = [
        models.User(nickname="양서연", region="유성구 온천2동", role="customer"),
        models.User(nickname="장민호", region="유성구 궁동", role="customer"),
        models.User(nickname="박지영", region="유성구 노은동", role="customer"),
        models.User(nickname="김수현", region="유성구 궁동", role="customer"),
    ]
    db.add_all(demo_users_for_txn)
    db.flush()

    pass_use_txns = []
    amounts_store1 = [1800, 2400, 3200, 1500, 2500]  # 동네커피 유성점
    amounts_store3 = [1200, 800, 1500]                # 우리분식
    amounts_store4 = [900, 1100]                       # 아삭샐러드

    for i, amt in enumerate(amounts_store1):
        pass_use_txns.append(
            models.Transaction(
                user_id=demo_users_for_txn[i % len(demo_users_for_txn)].id,
                type="pass_use", store_name="동네커피 유성점",
                amount=-amt, memo=None,
                created_at=now - timedelta(hours=i * 12 + 1),
            )
        )
    for i, amt in enumerate(amounts_store3):
        pass_use_txns.append(
            models.Transaction(
                user_id=demo_users_for_txn[i % len(demo_users_for_txn)].id,
                type="pass_use", store_name="우리분식",
                amount=-amt, memo=None,
                created_at=now - timedelta(hours=i * 8 + 2),
            )
        )
    for i, amt in enumerate(amounts_store4):
        pass_use_txns.append(
            models.Transaction(
                user_id=demo_users_for_txn[i % len(demo_users_for_txn)].id,
                type="pass_use", store_name="아삭샐러드",
                amount=-amt, memo=None,
                created_at=now - timedelta(hours=i * 10 + 3),
            )
        )
    db.add_all(pass_use_txns)
    db.commit()
    db.close()

    # 1. Dashboard
    print("=== Dashboard ===")
    r = client.get("/admin/dashboard")
    assert r.status_code == 200, f"dashboard failed: {r.status_code} {r.text}"
    data = r.json()
    print(f"  총 발급 쿠폰: {data['stats']['total_coupons_issued']}")
    print(f"  총 사용:      {data['stats']['total_coupons_used']}")
    print(f"  등록 가맹점:  {data['stats']['registered_stores']}")
    print(f"  보전 예상:    {data['stats']['estimated_subsidy']:,}원")
    print(f"  대기 신청:    {data['pending_applications']}건")
    print(f"  최근 활동:    {len(data['recent_activities'])}건")

    # 2. Applications - list
    print("\n=== Applications (pending) ===")
    r = client.get("/admin/applications?status=pending")
    assert r.status_code == 200
    data = r.json()
    print(f"  counts: {data['counts']}")
    for app_item in data["applications"]:
        print(f"  - {app_item['name']} ({app_item['category']}) [{app_item['status']}]")

    # 3. Application detail
    print("\n=== Application Detail (id=1) ===")
    r = client.get("/admin/applications/1")
    assert r.status_code == 200
    data = r.json()
    print(f"  {data['name']} / {data['business_number']} / {data['phone']}")

    # 4. Approve
    print("\n=== Approve (id=1) ===")
    r = client.post("/admin/applications/1/approve")
    assert r.status_code == 200
    print(f"  {r.json()}")

    # 5. Reject
    print("\n=== Reject (id=2) ===")
    r = client.post("/admin/applications/2/reject", json={"reason": "사업자등록증 확인 필요"})
    assert r.status_code == 200
    print(f"  {r.json()}")

    # 6. Settlements
    print("\n=== Settlements ===")
    r = client.get("/admin/settlements")
    assert r.status_code == 200
    data = r.json()
    print(f"  총 보전액: {data['stats']['total_subsidy']:,}원")
    print(f"  대기: {data['stats']['pending_amount']:,}원")
    print(f"  완료: {data['stats']['completed_amount']:,}원")
    for s in data["stores"]:
        print(f"  - {s['store_name']}: {s['transaction_count']}건, {s['subsidy_amount']:,}원 [{s['status']}]")

    # 7. Settlement detail
    if data["stores"]:
        sid = data["stores"][0]["store_id"]
        print(f"\n=== Settlement Detail (store_id={sid}) ===")
        r = client.get(f"/admin/settlements/{sid}")
        assert r.status_code == 200
        d = r.json()
        print(f"  {d['store_name']}: {d['transaction_count']}건, {d['total_subsidy']:,}원")
        for t in d["transactions"][:3]:
            print(f"    {t['timestamp']} {t['user_name']} {t['payment_amount']:,}원 -{t['discount_amount']:,}원")

    # 8. Settlement process
    if data["stores"]:
        sid = data["stores"][0]["store_id"]
        print(f"\n=== Process Settlement (store_id={sid}) ===")
        r = client.post(f"/admin/settlements/{sid}/process")
        assert r.status_code == 200
        print(f"  {r.json()}")

    # 9. Admin Passes
    print("\n=== Admin Passes ===")
    r = client.get("/admin/passes")
    assert r.status_code == 200
    data = r.json()
    for p in data["passes"]:
        tiers = ", ".join(f"{t['duration_days']}일/{t['price']:,}원" for t in p["price_tiers"])
        print(f"  - {p['name']} (scope={p['scope']}, {p['discount_rate']}%, {p['sale_status']}) [{tiers}]")

    # 10. Create pass
    print("\n=== Create Pass ===")
    r = client.post("/admin/passes", json={
        "name": "테스트 패스",
        "scope": "category",
        "scope_category": "음식점",
        "discount_rate": 5,
        "target_desc": "음식점 5% 할인",
        "price_tiers": [{"duration_days": 30, "price": 5000}, {"duration_days": 60, "price": 9000}],
        "sale_status": "on_sale",
    })
    assert r.status_code == 201
    print(f"  {r.json()}")

    # 11. Update pass
    new_id = r.json()["id"]
    print(f"\n=== Update Pass (id={new_id}) ===")
    r = client.put(f"/admin/passes/{new_id}", json={
        "name": "수정 테스트 패스",
        "scope": "category",
        "scope_category": "음식점",
        "discount_rate": 8,
        "target_desc": "음식점 8% 할인",
        "price_tiers": [{"duration_days": 30, "price": 6000}],
        "sale_status": "on_sale",
    })
    assert r.status_code == 200
    print(f"  {r.json()}")

    # 12. Validation test
    print("\n=== Validation: discount_rate=0 ===")
    r = client.post("/admin/passes", json={
        "name": "실패 패스",
        "scope": "all",
        "discount_rate": 0,
        "target_desc": "테스트",
        "price_tiers": [{"duration_days": 30, "price": 1000}],
    })
    assert r.status_code == 422
    print(f"  422 OK: validation error caught")

    print("\n[OK] All admin API tests passed!")
