from datetime import timedelta

from sqlalchemy.orm import Session

from app import config, models
from app.utils import utc_now
from web.auth import hash_password

DEMO_USER_ID = 100


STORE_LOCATION_FIXTURES = {
    1: {
        "address": "대전 유성구 대학로 99",
        "latitude": 36.36234,
        "longitude": 127.34486,
        "image_url": "https://placehold.co/600x400?text=Coffee",
        "phone_no": "042-111-1001",
    },
    2: {
        "address": "대전 유성구 궁동로 18",
        "latitude": 36.36157,
        "longitude": 127.35036,
        "image_url": "https://placehold.co/600x400?text=Roastery",
        "phone_no": "042-111-1002",
    },
    3: {
        "address": "대전 유성구 궁동 409-1",
        "latitude": 36.36018,
        "longitude": 127.34883,
        "image_url": "https://placehold.co/600x400?text=Bunsik",
        "phone_no": "042-111-1003",
    },
    4: {
        "address": "대전 유성구 온천로 45",
        "latitude": 36.35484,
        "longitude": 127.34179,
        "image_url": "https://placehold.co/600x400?text=Salad",
        "phone_no": "042-111-1004",
    },
    5: {
        "address": "대전 유성구 온천북로 33",
        "latitude": 36.35742,
        "longitude": 127.34291,
        "image_url": "https://placehold.co/600x400?text=Nail",
        "phone_no": "042-111-1005",
    },
    6: {
        "address": "대전 유성구 대학로151번길 12",
        "latitude": 36.36318,
        "longitude": 127.34967,
        "image_url": "https://placehold.co/600x400?text=Hair",
        "phone_no": "042-111-1006",
    },
}

def _backfill_store_locations(db: Session) -> None:
    changed = False
    for store_id, values in STORE_LOCATION_FIXTURES.items():
        store = db.get(models.Store, store_id)
        if store is None:
            continue
        for key, value in values.items():
            if getattr(store, key, None) in (None, ""):
                setattr(store, key, value)
                changed = True
    if changed:
        db.commit()


def run_seed(db: Session) -> None:
    """궁동/온천2동 상권 컨셉의 더미 데이터를 앱 최초 실행 시 1회 삽입한다."""
    if db.query(models.Store).first() is not None:
        # 기존 개발 DB는 create_all만으로 새 컬럼의 데모 값을 채울 수 없으므로
        # 지도 좌표와 패스 누적 할인 한도를 안전하게 보강한다.
        _backfill_store_locations(db)

        pass_limits = {
            1: config.PASS_ONEDAY_MAX_DISCOUNT,
            2: config.PASS_WEEKEND_CAFE_MAX_DISCOUNT,
            3: config.PASS_GUNGDONG_LOYALTY_MAX_DISCOUNT,
        }
        for pass_id, limit in pass_limits.items():
            pass_row = db.get(models.Pass, pass_id)
            if pass_row is not None and pass_row.max_discount_amount is None:
                pass_row.max_discount_amount = limit
        db.commit()
        return

    owners = [
        models.User(id=1, nickname="동네커피 사장님", region="유성구 온천2동", role="owner", owner_enabled=True),
        models.User(id=2, nickname="궁동로스터리 사장님", region="유성구 궁동", role="owner", owner_enabled=True),
        models.User(id=3, nickname="우리분식 사장님", region="유성구 궁동", role="owner", owner_enabled=True),
        models.User(id=4, nickname="아삭샐러드 사장님", region="유성구 온천2동", role="owner", owner_enabled=True),
        models.User(id=5, nickname="유성네일살롱 사장님", region="유성구 온천2동", role="owner", owner_enabled=True),
        models.User(id=6, nickname="궁동헤어스튜디오 사장님", region="유성구 궁동", role="owner", owner_enabled=True),
    ]
    demo_user = models.User(
        id=DEMO_USER_ID, nickname="홍길동", region="유성구 온천2동", role="customer"
    )
    db.add_all(owners + [demo_user])
    db.flush()

    stores = [
        models.Store(
            id=1, name="동네커피 유성점", category="카페", region="유성구 온천2동",
            business_hours="매일 08:00-22:00", owner_id=1, **STORE_LOCATION_FIXTURES[1],
        ),
        models.Store(
            id=2, name="궁동로스터리", category="카페", region="유성구 궁동",
            business_hours="매일 09:00-23:00", owner_id=2, **STORE_LOCATION_FIXTURES[2],
        ),
        models.Store(
            id=3, name="우리분식", category="음식점", region="유성구 궁동",
            business_hours="매일 10:00-21:00", owner_id=3, **STORE_LOCATION_FIXTURES[3],
        ),
        models.Store(
            id=4, name="아삭샐러드", category="음식점", region="유성구 온천2동",
            business_hours="매일 09:00-20:00", owner_id=4, **STORE_LOCATION_FIXTURES[4],
        ),
        models.Store(
            id=5, name="유성네일살롱", category="뷰티", region="유성구 온천2동",
            business_hours="매일 10:00-20:00", owner_id=5, **STORE_LOCATION_FIXTURES[5],
        ),
        models.Store(
            id=6, name="궁동헤어스튜디오", category="뷰티", region="유성구 궁동",
            business_hours="화-일 10:00-20:00", owner_id=6, **STORE_LOCATION_FIXTURES[6],
        ),
    ]
    db.add_all(stores)
    db.flush()

    policies = [
        models.StampPolicy(store_id=1, goal=5, reward="아메리카노 1잔 무료", condition="1일 1회·결제 시"),
        models.StampPolicy(store_id=2, goal=5, reward="핸드드립 1잔 무료", condition="1일 1회·결제 시"),
        models.StampPolicy(store_id=3, goal=5, reward="떡볶이 1인분 무료", condition="1일 1회·결제 시"),
        models.StampPolicy(store_id=4, goal=5, reward="샐러드 1개 무료", condition="1일 1회·결제 시"),
        models.StampPolicy(store_id=5, goal=5, reward="젤네일 케어 1회 무료", condition="1일 1회·결제 시"),
        models.StampPolicy(store_id=6, goal=5, reward="헤어 트리트먼트 1회 무료", condition="1일 1회·결제 시"),
    ]
    db.add_all(policies)

    now = utc_now()
    coupons = [
        models.Coupon(
            store_id=3, type="discount_rate", title="전 메뉴 10% 할인", value=10,
            target="전 메뉴", valid_until=now + timedelta(days=12), time_limit_hours=None,
            store_only=True, min_payment=0, max_discount=2000,
        ),
        models.Coupon(
            store_id=4, type="discount_amount", title="1,000원 할인", value=1000,
            target="전 메뉴", valid_until=now + timedelta(days=7), time_limit_hours=None,
            store_only=True, min_payment=5000, max_discount=None,
        ),
        models.Coupon(
            store_id=5, type="time_limited", title="2시간 내 사용", value=2,
            target="전 상품", valid_until=None, time_limit_hours=2,
            store_only=True, min_payment=0, max_discount=None,
        ),
        # 결제 혜택 계산(8-6) 데모용: 우리분식(store_id=3)에 정률+정액 쿠폰을 함께 배치
        models.Coupon(
            store_id=3, type="discount_amount", title="1,000원 할인", value=1000,
            target="전 메뉴", valid_until=now + timedelta(days=7), time_limit_hours=None,
            store_only=True, min_payment=5000, max_discount=None,
        ),
    ]
    db.add_all(coupons)

    # 가격/할인율은 차후 바뀔 수 있어 app/config.py의 환경변수로 뺐다
    # (PASS_ONEDAY_PRICE 등). duration_days·scope 같은 구조적 값만 여기 고정한다.
    passes = [
        models.Pass(
            id=1, name="유성 원데이 패스", scope="all", period_type="one_day",
            duration_days=1, price=config.PASS_ONEDAY_PRICE,
            discount_rate=config.PASS_ONEDAY_DISCOUNT_RATE,
            max_discount_amount=config.PASS_ONEDAY_MAX_DISCOUNT,
            target_desc="관광지·카페·음식점 10% 할인",
            scope_category=None, scope_store_id=None,
        ),
        models.Pass(
            id=2, name="주말 카페 패스", scope="category", period_type="period",
            duration_days=30, price=config.PASS_WEEKEND_CAFE_PRICE,
            discount_rate=config.PASS_WEEKEND_CAFE_DISCOUNT_RATE,
            max_discount_amount=config.PASS_WEEKEND_CAFE_MAX_DISCOUNT,
            target_desc="카페 결제 10% 할인",
            scope_category="카페", scope_store_id=None,
        ),
        models.Pass(
            id=3, name="궁동 단골패스", scope="store", period_type="period",
            duration_days=30, price=config.PASS_GUNGDONG_LOYALTY_PRICE,
            discount_rate=config.PASS_GUNGDONG_LOYALTY_DISCOUNT_RATE,
            max_discount_amount=config.PASS_GUNGDONG_LOYALTY_MAX_DISCOUNT,
            target_desc="동네커피 유성점 전용 15% 할인",
            scope_category=None, scope_store_id=1,
        ),
    ]
    db.add_all(passes)

    notifications = [
        models.Notification(
            user_id=DEMO_USER_ID,
            title="스탬프 4/5 적립!",
            body="동네커피 유성점 스탬프가 4/5예요. 한 번 더 방문하면 리워드를 받아요.",
            read=False,
            created_at=now - timedelta(hours=2),
        ),
        models.Notification(
            user_id=DEMO_USER_ID,
            title="쿠폰 만료 임박",
            body="우리분식 10% 할인 쿠폰이 곧 만료돼요. 서둘러 사용해보세요.",
            read=False,
            created_at=now - timedelta(hours=20),
        ),
        models.Notification(
            user_id=DEMO_USER_ID,
            title="패스 구매 완료",
            body="궁동 단골패스 구매가 완료됐어요. 결제 시 QR을 스캔하고 패스를 선택해보세요.",
            read=False,
            created_at=now - timedelta(days=1),
        ),
    ]
    db.add_all(notifications)

    # 데모 유저가 궁동로스터리에서는 이미 적립을 시작한 상태로 두어 목록 화면에서
    # stamp_summary가 채워진 매장/비어 있는 매장을 함께 보여준다.
    db.add(
        models.StampCard(
            user_id=DEMO_USER_ID,
            store_id=2,
            current=2,
            updated_at=now - timedelta(days=1),
        )
    )

    # 패스 기간별 가격 (PassPriceTier) - 패스 정보 테이블 동기화를 위한 기본 데이터
    price_tiers = [
        models.PassPriceTier(pass_id=1, duration_days=1, price=config.PASS_ONEDAY_PRICE),
        models.PassPriceTier(pass_id=2, duration_days=30, price=config.PASS_WEEKEND_CAFE_PRICE),
        models.PassPriceTier(pass_id=2, duration_days=60, price=22000),
        models.PassPriceTier(pass_id=2, duration_days=90, price=30000),
        models.PassPriceTier(pass_id=3, duration_days=30, price=config.PASS_GUNGDONG_LOYALTY_PRICE),
    ]
    db.add_all(price_tiers)

    # 기본 관리자 계정
    db.add(
        models.AdminUser(
            username="admin",
            hashed_password=hash_password("admin1234"),
            name="유성구청 관리자",
        )
    )

    db.commit()
