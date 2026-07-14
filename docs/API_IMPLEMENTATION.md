# 유성으로 (ToYuseong) — 구현 API 명세서

> 이 문서는 **지금 코드(`app/`)가 실제로 하는 일**을 기준으로 쓴 명세서다.
> 기획 원본은 [`API.md`](./API.md)이며, 거기 없던 결정(스코프 애매한 부분, 데이터 모델 불일치 등)을 구현하면서 내린 선택은 이 문서에 명시했다.
> `API.md`와 이 문서가 다르면 **이 문서가 현재 서버 동작을 더 정확히 반영**한다. `API.md`는 최초 기획 의도를 보여주는 참고 문서로 남겨둔다.

---

## 0. 기술 스택

| 영역          | 선택                                                      | 비고                                                                                                      |
| ------------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 언어/런타임   | Python 3.11+                                              |                                                                                                           |
| 웹 프레임워크 | **FastAPI**                                               | `fastapi[standard]` (Swagger `/docs` 자동 제공)                                                           |
| ORM           | **SQLAlchemy 2.0, 동기 방식**                             | `Mapped`/`mapped_column` 스타일. async/`AsyncSession` 미사용                                              |
| DB            | **SQLite** (`sqlite:///./toyuseong.db`)                   | 앱 시작 시 `Base.metadata.create_all`로 테이블 생성. 별도 마이그레이션 도구(Alembic 등) 없음              |
| 스키마/검증   | **Pydantic v2**                                           | `ConfigDict(from_attributes=True)`, `Annotated[..., PlainSerializer]`로 datetime → `"...Z"` 문자열 직렬화 |
| 서버 실행     | `fastapi dev app/main.py` (개발) / `uvicorn app.main:app` |                                                                                                           |
| 인증          | 없음(OAuth 미구현). `X-User-Id: <int>` 헤더만 신뢰        | §2 참고                                                                                                   |
| 설정          | 표준 라이브러리 `os.environ` (`app/config.py`)            | 별도 설정 라이브러리(pydantic-settings, python-dotenv) 미사용                                             |
| 테스트        | `pytest` + FastAPI `TestClient`(httpx)                    | in-memory SQLite(`sqlite://` + `StaticPool`)로 매 테스트 격리                                             |
| CORS          | `starlette.CORSMiddleware`, `allow_origins=["*"]`         | 개발 편의를 위해 전체 허용                                                                                |

프로젝트 구조:

```
app/
  main.py          # FastAPI 앱, CORS, 공통 에러 핸들러, 라우터 등록
  database.py       # engine, SessionLocal, Base, get_db 의존성
  models.py         # SQLAlchemy ORM 모델
  schemas.py        # Pydantic 요청/응답 스키마 (+ UtcDatetime 직렬화 타입)
  config.py         # os.environ 기반 설정값 (현재: 패스 가격/할인율)
  utils.py          # 공통 유틸(시간, d_day 계산, 인증 의존성, 만료 동기화)
  seed.py           # 데모 데이터 시드 (최초 1회)
  routers/
    stores.py   coupons.py   stamps.py   checkout.py   passes.py   me.py   auth.py(스텁)
  tests/
    conftest.py  test_stamps.py  test_checkout.py
```

---

## 1. 공통 규약

### 에러 응답

모든 4xx는 다음 형식:

```json
{ "error": "snake_case_code", "message": "사람이 읽는 한글 안내" }
```

일부 에러는 부가 필드를 더 싣는다 (예: `already_used`는 `used_at`, `coupon_expired`(사용 시)는 `expired_at`).

### 날짜/시간

서버는 내부적으로 tzinfo 없는 UTC datetime을 쓰고, JSON으로 나갈 때는 항상 `"%Y-%m-%dT%H:%M:%SZ"` 포맷 문자열로 직렬화한다 (`app/utils.py:iso_z`). `d_day`는 `(대상일 - 오늘).days`로 서버가 계산해서 정수로 내려준다.

### 목록 응답

비어 있으면 `[]`. `null`로 내려가지 않는다.

---

## 2. 인증 — `X-User-Id` 헤더만 사용

OAuth/JWT 없음. `POST /auth/google`은 라우터 파일만 존재하고 **엔드포인트가 없다** (`app/routers/auth.py`는 빈 스텁이며 `main.py`에 등록조차 되어 있지 않음). 실제 로그인/회원가입 플로우가 없고, `seed.py`가 심어둔 유저(데모 고객 `id=100`, 매장 사장님 `id=1~6`)만 존재한다.

두 종류의 의존성이 있다 (`app/utils.py`):

- **`require_user_id`** — 필수 인증. 다음 두 경우 `401`을 던진다.
  - 헤더 자체가 없음 → `{"error":"unauthorized","message":"로그인이 필요해요"}`
  - 헤더는 있지만 그 id의 `User`가 DB에 없음 → `{"error":"invalid_user","message":"유효하지 않은 사용자예요"}`
  - 이걸 통과하면 이후 로직은 유저가 실존한다고 가정해도 된다.
- **`get_optional_user_id`** — 선택적 인증. 헤더가 없어도 통과하며, 있으면 값을 그대로 돌려준다 (DB 존재 여부 검증 안 함 — 목록 조회의 "내 정보 얹기" 용도라 실패해도 그냥 개인화가 빠질 뿐 에러는 아님).

| 엔드포인트                                                                   | 인증                                                                  |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `GET /stores`, `GET /stores/{id}`                                            | 선택 (있으면 `stamp_summary`/`current`/`stamped_today` 채움)          |
| `GET /coupons`                                                               | 선택 (있으면 `claimed_by_me` 채움)                                    |
| `GET /passes`, `GET /passes/{id}`                                            | 선택 (있으면 `owned` 채움)                                            |
| `POST /stamps`                                                               | **헤더 아님** — body의 `customer_token`으로 유저 식별 (아래 3-2 참고) |
| 그 외 `/me/*`, `/coupons/{id}/claim`, `/checkout/*`, `/passes/{id}/purchase` | 필수                                                                  |

---

## 3. 엔드포인트

### 3-1. `GET /stores` — 매장 목록

Query: `region?`(str), `category?`(카페\|음식점\|뷰티\|기타\|all, 기본 all), `sort?`(popular\|recent, 기본 popular — 현재 `recent`는 `id desc`, `popular`은 `id asc`로만 구현. 실제 인기도/최신순 지표는 없음)

```json
{ "stores": [ { "id": 1, "name": "동네커피 유성점", "category": "카페", "region": "유성구 온천2동", "stamp_summary": { "current": 3, "goal": 5 } | null } ] }
```

### 3-2. `GET /stores/{store_id}` — 매장 상세

```json
{
  "id": 1,
  "name": "...",
  "category": "카페",
  "region": "...",
  "business_hours": "...",
  "stamp": {
    "goal": 5,
    "current": 3,
    "reward": "...",
    "condition": "...",
    "stamped_today": false
  }
}
```

`404 store_not_found`

### 3-3. `POST /stamps` — 스탬프 적립 ⭐

인증 없이 body만으로 동작 (매장 사장님 단말이 손님 QR을 스캔해서 호출하는 흐름이라 손님의 로그인 세션과 무관).

```json
{ "store_id": 1, "customer_token": "eyJ1c2VyIjoxMDB9", "amount": 4500 }
```

- `customer_token`: **base64(JSON `{"user": <user_id>}`)** — QR 방식이 미확정이라 임시로 정한 규약. 표준/urlsafe base64 둘 다 시도.
- `amount`: 참고용 숫자. 저장/계산에 쓰이지 않음(스탬프는 방문당 정확히 1개).

```json
{
  "store_name": "동네커피 유성점",
  "current": 1,
  "goal": 5,
  "reward_reached": false,
  "reward": null,
  "card_created": true,
  "reward_coupon": null,
  "card_reset_to": null,
  "message": "동네커피 유성점 스탬프가 시작됐어요"
}
```

5/5 도달 시 (예시):

```json
{
  "store_name": "...",
  "current": 5,
  "goal": 5,
  "reward_reached": true,
  "reward": "아메리카노 1잔 무료",
  "card_created": false,
  "reward_coupon": {
    "user_coupon_id": 120,
    "title": "아메리카노 1잔 무료 쿠폰",
    "d_day": 30
  },
  "card_reset_to": 0,
  "message": "5개 완성! 리워드 쿠폰이 발급됐어요"
}
```

동작:

1. `customer_token` 디코딩 실패 / 해당 유저 없음 / `store_id` 없음 / 해당 매장에 `StampPolicy` 없음 → **400 `invalid_qr`**
2. 오늘 이미 적립했으면(카드 `updated_at`이 오늘) → **409 `already_stamped_today`**
3. 카드가 없으면 새로 만들고 `card_created:true`
4. `current += 1`. `current >= goal`이면: `reward` 텍스트로 새 리워드용 `Coupon`을 하나 발급(`type=discount_amount, value=0`, 유효기간 30일) → 그걸 가리키는 `UserCoupon`을 `active`로 생성 → `StampCard.current`를 0으로 리셋. 이 모든 게 한 트랜잭션.
5. `Transaction` 기록: 항상 `stamp_earn` 1건, 리워드 발급 시 `reward_issue` 1건 추가.

### 3-4. `GET /coupons` — 쿠폰 탐색

Query: `region?`, `category?`, `sort?` (매장 목록과 동일 패턴)

```json
{
  "coupons": [
    {
      "id": 10,
      "store_name": "우리분식",
      "type": "discount_rate",
      "title": "전 메뉴 10% 할인",
      "value": 10,
      "target": "전 메뉴",
      "valid_until": "...Z",
      "d_day": 12,
      "time_limit_hours": null,
      "store_only": true,
      "claimed_by_me": false
    }
  ]
}
```

`type=time_limited`면 `valid_until`/`d_day`는 `null`, `time_limit_hours`만 값.

### 3-5. `POST /coupons/{coupon_id}/claim` — 쿠폰 받기

```json
{
  "user_coupon_id": 55,
  "coupon_id": 10,
  "status": "active",
  "claimed_at": "...Z",
  "message": "쿠폰함에 담겼어요"
}
```

`404 coupon_not_found` (id 자체가 없을 때 — 원본 기획엔 없던 케이스지만 방어적으로 추가) · `409 already_claimed`(이미 한 번이라도 받은 적 있으면, 상태 무관) · `410 coupon_expired`(발급기한 지남; `time_limited`는 발급기한 개념이 없어 항상 통과)

### 3-6. `GET /me/coupons` — 내 보유 쿠폰

Query: `status?`(active\|used\|expired\|all, 기본 active). `claimed_at` 내림차순 정렬.
`status`에 따라 `used_at`/`expired_at` 중 하나만 값 (§4 참고).

### 3-7. `GET /me/coupons/{user_coupon_id}` — 보유 쿠폰 상세

```json
{
  "user_coupon_id": 55,
  "store": {
    "name": "...",
    "category": "...",
    "region": "...",
    "business_hours": "..."
  },
  "type": "...",
  "title": "...",
  "value": 10,
  "target": "...",
  "status": "active",
  "used_at": null,
  "expired_at": null,
  "valid_until": "...Z",
  "d_day": 12,
  "store_only": true,
  "usage_note": "발급 매장에서만 사용 가능"
}
```

본인 소유가 아니거나 없는 id → `404 user_coupon_not_found`

### 3-8. `POST /me/coupons/{user_coupon_id}/use` — 쿠폰 사용

```json
{
  "user_coupon_id": 55,
  "status": "used",
  "used_at": "...Z",
  "message": "쿠폰이 사용되었어요"
}
```

`404 user_coupon_not_found` · `409 already_used`(+`used_at`) · `410 coupon_expired`(+`expired_at`)

이 API와 `POST /checkout`(coupon 계열)은 **서로 독립된 소진 경로**다. 결제 화면에서 쓰면 `/checkout`이, 사장님이 직접 쿠폰만 스캔해서 처리하면 이 API가 소진시킨다. 같은 쿠폰을 두 경로로 중복 사용할 수는 없다(한쪽에서 `used`가 되면 다른 쪽은 409/410).

### 3-9. `GET /checkout/benefits` — 결제 혜택 계산 ⭐

Query: `store_id`(int, 필수), `amount`(int, 필수) · 인증 필수

보유 중인 활성 쿠폰(이 매장 것만, `store_only` 기준) + 보유 중인 활성 패스(scope가 이 매장에 적용되는 것만) + 항상 마지막에 `none`을 합쳐 `benefits[]`로 반환.

```json
{
  "store_name": "우리분식",
  "amount": 18000,
  "benefits": [
    {
      "benefit_id": "coupon:55",
      "kind": "coupon_rate",
      "title": "10% 할인 쿠폰",
      "desc": "이 매장 발급분 · 최대 2,000원",
      "discount": 1800,
      "selectable": true,
      "reason": null
    },
    {
      "benefit_id": "coupon:60",
      "kind": "coupon_amount",
      "title": "1,000원 할인 쿠폰",
      "desc": "5,000원 이상 · 이 매장 발급분",
      "discount": 1000,
      "selectable": true,
      "reason": null
    },
    {
      "benefit_id": "pass:88",
      "kind": "pass",
      "title": "주말 카페 패스",
      "desc": "카페 10% 할인 · 보유 패스 · 전 매장 공통",
      "discount": 1800,
      "selectable": true,
      "reason": null
    },
    {
      "benefit_id": "none",
      "kind": "none",
      "title": "사용 안함",
      "desc": "원가 그대로 결제",
      "discount": 0,
      "selectable": true,
      "reason": null
    }
  ]
}
```

계산 규칙:

- `discount_rate`: `round(amount * value / 100)`, `max_discount` 있으면 상한 적용(넘으면 `reason:"최대 N원 적용"`)
- `discount_amount`: `min(value, amount)`
- `amount < min_payment`면 `selectable:false, discount:0, reason:"N원 이상부터 사용 가능"`
- `time_limited` 쿠폰은 결제 혜택 목록에서 **제외**(명세의 `benefit.kind`에 대응 타입이 없음)
- 패스 `discount`는 `round(amount * discount_rate / 100)`, 상한 없음
- `404 store_not_found`

### 3-10. `POST /checkout` — 결제(데모)

```json
{
  "store_id": 1,
  "amount": 18000,
  "benefit_id": "coupon:55",
  "method": "easy_pay"
}
```

**항상 200**으로 응답하고 `result`로 성공/실패를 구분한다(검증 실패도 4xx가 아니라 `result:"fail"`로 응답 — 인증 실패(401)만 예외).

- `benefit_id="none"` → 원가 그대로 성공, Transaction 기록 없음(해당 타입 없음)
- `benefit_id="coupon:{id}"` → 소유/매장 일치/미사용/미만료/`min_payment` 재검증 후 `used` 처리 + `coupon_use` Transaction(`amount`는 할인액의 음수)
- `benefit_id="pass:{id}"` → 소유/scope 일치/활성 재검증 후 할인 계산(패스는 소진되지 않음, `consumed:false`) + `pass_use` Transaction
- 그 외 → `{"result":"fail","message":"..."}`

> 참고: 명세 문구상 "성공/실패 시뮬레이션"이 있지만, 테스트 재현성을 위해 **무작위 실패는 넣지 않았다**. 실패는 전부 검증 실패(매장 없음, 쿠폰/패스 소유 아님, 만료 등) 사유가 있을 때만 발생한다.

### 3-11. `GET /passes` — 패스 마켓

Query: `region?`(현재 필터링에 사용되지 않음 — Pass 모델에 region 개념이 없어서 파라미터만 받고 무시함)

```json
{
  "passes": [
    {
      "id": 1,
      "name": "유성 원데이 패스",
      "scope": "all",
      "period_type": "one_day",
      "duration_days": 1,
      "price": 2900,
      "discount_rate": 10,
      "target_desc": "...",
      "owned": false
    }
  ]
}
```

### 3-12. `GET /passes/{pass_id}` — 패스 상세

```json
{
  "id": 2,
  "name": "주말 카페 패스",
  "scope": "category",
  "discount_rate": 10,
  "target_desc": "...",
  "price_options": [{ "duration_days": 30, "price": 9900 }],
  "usage_note": "...",
  "notice": "할인 차액은 유성구청이 보전해요",
  "owned": false
}
```

> **알려진 단순화**: 기획 문서(API.md 8-2/8-3)는 패스 하나가 여러 기간 옵션(예: 1일 1,500원~30일 9,900원)을 갖는 것처럼 예시가 나오지만, 데이터 모델(API.md 7절)은 패스당 `duration_days`/`price` 단일 값만 정의한다. 두 절이 서로 다른 숫자를 예시로 들어 모델을 확정할 수 없었고, 데이터 모델(§7)을 기준으로 삼아 **패스당 단일 가격**만 지원하도록 구현했다. `price_options`는 그 단일 값을 담은 1개짜리 배열로 내려간다.

`404 pass_not_found`

### 3-13. `GET /me/passes` — 내 패스

Query: `status?`(active\|expired\|all, 기본 active). `expires_at` 내림차순.

### 3-14. `POST /passes/{pass_id}/purchase` — 패스 구매

```json
{ "duration_days": 30 }
```

```json
{
  "user_pass_id": 88,
  "name": "주말 카페 패스",
  "status": "active",
  "expires_at": "...Z",
  "paid": 9900,
  "message": "패스 구매가 완료됐어요"
}
```

> **알려진 단순화**: 위 단일-가격 구조 때문에 body의 `duration_days`는 **검증하지 않고 무시**한다. 항상 그 패스에 고정된 `duration_days`/`price`로 구매 처리된다. `Transaction`에 `pass_purchase`(양수 `amount` = 결제액, `store_name: null`, `memo`=패스명) 1건 기록.
> `404 pass_not_found`

### 3-15. `GET /me` — 내 정보

```json
{
  "id": 100,
  "nickname": "홍길동",
  "region": "유성구 온천2동",
  "role": "customer",
  "unread_notifications": 3
}
```

`unread_notifications`는 §3-16 알림 중 `read=false` 개수를 실제로 센 값이다.

### 3-16. `GET /me/notifications` — 알림 목록 ⚠️ 기획(API.md)에 없는 목업 API

사용자가 명시적으로 요청해서 추가한, **알림 아이콘을 눌렀을 때 보여줄 가짜 데이터 API**다. `docs/API.md`에는 없다.

```json
{
  "notifications": [
    {
      "id": 3,
      "title": "패스 구매 완료",
      "body": "...",
      "read": false,
      "created_at": "...Z"
    },
    {
      "id": 2,
      "title": "쿠폰 만료 임박",
      "body": "...",
      "read": false,
      "created_at": "...Z"
    },
    {
      "id": 1,
      "title": "스탬프 4/5 적립!",
      "body": "...",
      "read": false,
      "created_at": "...Z"
    }
  ]
}
```

- 최신순 정렬.
- **부작용**: 응답을 만든 시점의 읽음 여부를 그대로 내려준 뒤, 그 알림들을 서버에서 읽음(`read=true`) 처리한다. 즉 이 API를 한 번 호출하면(=벨 아이콘을 누르면) 다음 `GET /me`의 `unread_notifications`는 0이 된다.
- 시드 데이터로 데모 유저(`id=100`)에게 3개가 미리 들어있다.

### 3-17. `GET /me/transactions` — 이용내역

Query: `filter?`(all\|coupon\|stamp\|pass, 기본 all), `cursor?`(opaque string)

```json
{
  "transactions": [
    {
      "id": 501,
      "type": "pass_use",
      "store_name": "...",
      "amount": -1800,
      "memo": null,
      "created_at": "...Z"
    }
  ],
  "next_cursor": "eyJvZmZzZXQiOjIwfQ=="
}
```

- `filter` 그룹핑: `coupon` → `coupon_use/coupon_claim/coupon_expire`, `stamp` → `stamp_earn/reward_issue`, `pass` → `pass_use/pass_purchase`
- `cursor`: `base64(JSON {"offset": N})`, 페이지 크기 20. `next_cursor`는 더 있을 때만 값, 없으면 `null`.
- `created_at` 내림차순(최신 먼저) 정렬.
- `coupon_expire`는 현재 어떤 코드 경로도 생성하지 않는다(만료는 지연 평가만 하고 별도 Transaction을 남기지 않음) — 필터/응답 스키마상 자리는 마련해뒀다.

---

## 4. 조건부 필드 규칙

### `user_coupon.status` → `used_at` / `expired_at`

| status  | used_at  | expired_at |
| ------- | -------- | ---------- |
| active  | null     | null       |
| used    | datetime | null       |
| expired | null     | datetime   |

만료 판정은 **조회 시점 지연 평가**다(`app/utils.py:sync_user_coupon_status`) — 별도 배치/크론 없이, `/me/coupons`, `/me/coupons/{id}`, `/me/coupons/{id}/use`, `/checkout/benefits`, `/checkout`을 호출할 때마다 그 쿠폰이 기간을 넘겼는지 확인해서 필요하면 그 순간 `active → expired`로 전환하고 커밋한다. `discount_rate`/`discount_amount`는 `Coupon.valid_until` 기준, `time_limited`는 `claimed_at + time_limit_hours` 기준. 패스도 동일한 방식(`sync_user_pass_status`)으로 `active → expired` 전환된다.

### `stamps` 응답 → `reward` / `reward_coupon` / `card_reset_to`

| reward_reached | reward | reward_coupon | card_reset_to |
| -------------- | ------ | ------------- | ------------- |
| false          | null   | null          | null          |
| true           | string | object        | 0             |

---

## 5. 데이터 모델

`app/models.py` 기준. API.md §2/§7과 다르거나 추가된 부분만 표시.

| 테이블           | 비고                                                                                                                                                                                                                    |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `users`          | id, nickname, region, role(customer\|owner), created_at                                                                                                                                                                 |
| `stores`         | id, name, category, region, business_hours, owner_id                                                                                                                                                                    |
| `stamp_policies` | store_id당 1개. id, store_id, goal, reward, condition                                                                                                                                                                   |
| `stamp_cards`    | 유저×매장. id, user_id, store_id, current, updated_at(마지막 적립 시각 = 오늘 적립 여부 판정 기준)                                                                                                                      |
| `coupons`        | API.md §2 필드 + **`min_payment`(int, 기본 0)**, **`max_discount`(int\|null)** — §7 추가분 반영. 스탬프 리워드 발급 시에도 이 테이블에 개별 row가 새로 생긴다                                                           |
| `user_coupons`   | id, user_id, coupon_id, status, claimed_at, used_at, expired_at                                                                                                                                                         |
| `passes`         | API.md §7 필드 + **`usage_note`**(기본 문구 내장) + 내부 전용 **`scope_category`**, **`scope_store_id`**(scope가 category/store일 때 실제 대상을 서버가 알아야 결제 혜택 계산이 가능해서 추가. API 응답에는 노출 안 함) |
| `user_passes`    | id, user_id, pass_id, status(active\|expired), purchased_at, expires_at                                                                                                                                                 |
| `transactions`   | API.md §7 그대로                                                                                                                                                                                                        |
| `notifications`  | ⚠️ API.md에 없음. id, user_id, title, body, read(bool), created_at                                                                                                                                                      |

---

## 6. 환경변수 (`app/config.py`)

패스 가격/할인율은 운영 중 바뀔 가능성이 높아 하드코딩하지 않고 환경변수로 뺐다. 지정하지 않으면 오른쪽 기본값을 쓴다.

| 변수                                  | 기본값 | 대상                       |
| ------------------------------------- | ------ | -------------------------- |
| `PASS_ONEDAY_PRICE`                   | 2900   | 유성 원데이 패스 가격      |
| `PASS_ONEDAY_DISCOUNT_RATE`           | 10     | 유성 원데이 패스 할인율(%) |
| `PASS_WEEKEND_CAFE_PRICE`             | 9900   | 주말 카페 패스 가격        |
| `PASS_WEEKEND_CAFE_DISCOUNT_RATE`     | 10     | 주말 카페 패스 할인율(%)   |
| `PASS_GUNGDONG_LOYALTY_PRICE`         | 4900   | 궁동 단골패스 가격         |
| `PASS_GUNGDONG_LOYALTY_DISCOUNT_RATE` | 15     | 궁동 단골패스 할인율(%)    |

사용 예:

```bash
PASS_ONEDAY_PRICE=3900 PASS_ONEDAY_DISCOUNT_RATE=15 fastapi dev app/main.py
```

`duration_days`/`scope`/`target_desc` 등 구조적인 값은 환경변수화하지 않고 `seed.py`에 고정돼 있다(바뀌면 스탬프/패스 로직 자체에 영향을 주는 값이라 가격과는 성격이 다르다고 판단).

---

## 7. 시드 데이터 (`app/seed.py`, 최초 실행 시 1회)

- 유저: 데모 고객 `id=100`("홍길동", customer) + 매장 사장님 6명(`id=1~6`, owner)
- 매장 6개(궁동/온천2동 상권): 카페 2(동네커피 유성점, 궁동로스터리) · 음식점 2(우리분식, 아삭샐러드) · 뷰티 2(유성네일살롱, 궁동헤어스튜디오) — 매장마다 `StampPolicy`(목표 5, 리워드 문구) 1개
- 쿠폰 4개: 우리분식에 `discount_rate 10%(상한 2,000원)` + `discount_amount 1,000원(최소 5,000원)`을 함께 배치(결제 혜택 계산 예시를 그대로 재현하기 위함), 아삭샐러드에 `discount_amount`, 유성네일살롱에 `time_limited`
- 패스 3개: 유성 원데이 패스(scope=all) · 주말 카페 패스(scope=category, 카페) · 궁동 단골패스(scope=store, 동네커피 유성점 전용) — scope별 혜택 매칭 로직을 각각 검증할 수 있도록 구성
- 알림 3개(데모 고객, 전부 `read=false`)
- 데모 고객은 궁동로스터리에서 이미 2/5 적립된 상태로 시작(목록 화면에서 `stamp_summary`가 채워진 매장/빈 매장을 동시에 보여주기 위함)

---

## 8. 알려진 제약/단순화 (구현 시 확정한 선택)

1. **회원가입/로그인 없음.** `POST /auth/google`은 라우터 스텁만 존재, 실제 등록 로직 없음. 새 `X-User-Id`를 보내면 (다른 값과 무관하게) `require_user_id`가 `401 invalid_user`로 막는다.
2. **패스 가격은 패스당 단일 값.** §3-12 참고 — 기획 문서의 목록/상세 예시 수치가 서로 달라서 데이터 모델(§7) 기준으로 단일화했다.
3. **결제 랜덤 실패 없음.** 검증 실패 사유가 있을 때만 `result:"fail"`.
4. **알림 API는 목업.** `docs/API.md`에 없는 기능이며, "가라" 데이터 3건 + 조회 시 자동 읽음 처리만 구현했다. 정식 명세로 편입하려면 API.md에도 추가 반영이 필요하다.
5. **`coupon_expire` Transaction 미생성.** 만료는 지연 평가만 하고 별도 이력을 남기지 않는다(스키마/필터 자리는 있음).

# API 명세서(관리자)

# Structure

## CouponRequest

```python
CouponRequest = CouponRequestPercent | CouponRequestStamp | CouponRequestFixed
```

### 구현

#### CouponRequestPercent

| Field        | Type               | Required | Description                 |
| ------------ | ------------------ | -------- | --------------------------- |
| type         | Literal[“percent”] | O        | 요청 타입                   |
| sale_percent | float              | O        | 할인률                      |
| sale_max     | int                | X        | 최대 할인 상한              |
| is_apply_all | boolean            | X        | 적용 대상(전 메뉴 적용인가) |
| expiry_date  | datetime           | O        | 만료 기간                   |

#### CouponRequestStamp

| Field             | Type             | Required | Description               |
| ----------------- | ---------------- | -------- | ------------------------- |
| type              | Literal[“stamp”] | O        | 요청 타입                 |
| stamp_max_require | int              | O        | 적립 목표 개수            |
| reward_content    | string           | O        | 리워드 내용               |
| is_visit_stamp    | boolean          | X        | 적립 단위(방문 시 찍는가) |
| expiry_date       | datetime         | O        | 만료 기간                 |

#### CouponRequestFixed

| Field              | Type             | Required | Description     |
| ------------------ | ---------------- | -------- | --------------- |
|                    | Literal[“fixed”] | O        | 요청 타입       |
| sale_price         | int              | O        | 할인 금액       |
| min_buy_price      | int              | O        | 최소 결제 조건  |
| expiry_date        | datetime         | O        | 만료 기간       |
| coupon_num         | int              | X        | 쿠폰 발급 수량  |
| is_coupon_infinity | boolean          | X        | 무제한 쿠폰인가 |

## CouponResponse

```python
CouponResponse = CouponResponsePercent | CouponResponseStamp | CouponResponseFixed
```

### 구현

#### CouponResponsePercent

```
{
    "id":1,
    "type":"percent",
    "sale_percent":10,
    "sale_max":5000,
    "is_apply_all":true,
    "expiry_date":"2026-08-31T23:59:59Z"
}
```

#### CouponResponseStamp

```
{
    "id":2,
    "type":"stamp",
    "stamp_max_require":10,
    "reward_content":"아메리카노 1잔 무료",
    "is_visit_stamp":false,
    "expiry_date":"2026-12-31T23:59:59Z"
}
```

#### CouponResponseFixed

```
{
    "id":3,
    "type":"fixed",
    "sale_price":3000,
    "min_buy_price":15000,
    "coupon_num":100,
    "is_coupon_infinity":false,
    "expiry_date":"2026-09-30T23:59:59Z"
}
```

# Enum

## ShopCategory

- cafe
- rest
- beauty
- etc

# 공통

Base URL: “/admin”

?은 optional입니다.

# Register API

## POST /register

## Description

사업을 등록한다.

### Authentication

Bearer JWT 필요

### Headers

| Name          | Type   | Required | Description  |
| ------------- | ------ | -------- | ------------ |
| Authorization | string | O        | Bearer <JWT> |

### Request Body

| Field          | Type         | Required | Description    |
| -------------- | ------------ | -------- | -------------- |
| name           | string       | O        | 매장명         |
| register_num   | string       | O        | 사업자등록번호 |
| category       | ShopCategory | O        | 매장 카테고리  |
| region         | string       | O        | 매장 지역      |
| business_hours | string       | X        | 영업시간       |
| phone_no       | string       | O        | 전화번호       |

### Example Request

```json
{
  "name": "맛있는 식당",
  "register_num": "123-45-67890",
  "category": "rest",
  "region": "유성구 온천2동",
  "business_hours": "매일 10:00 ~ 21:00",
  "phone_no": "010-1234-5678"
}
```

### Success

#### 201 Created

```json
{
  "id": 100,
  "name": "맛있는 식당",
  "category": "rest",
  "region": "유성구 온천2동",
  "business_hours": "매일 10:00 ~ 21:00",
  "phone_no": "010-1234-5678"
}
```

---

### Errors

#### 400 Bad Request

```json
{
  "error": "require_is_empty",
  "message": "필수 데이터가 없습니다."
}
```

#### 401 Unauthorized

```json
{
  "error": "unauthorized",
  "message": "로그인이 필요합니다."
}
```

#### 409 Conflict

```json
{
  "error": "already_registered",
  "message": "이미 등록된 사업자입니다."
}
```

# Coupons API

PATCH 또는 PUT은 제외(데모).

## POST /coupons

### Description

새로운 쿠폰 또는 스탬프 정책을 생성한다.

### Authentication

Bearer JWT 필요

### Headers

| Name          | Type   | Required | Description  |
| ------------- | ------ | -------- | ------------ |
| Authorization | string | O        | Bearer <JWT> |

### Request Body

`CouponRequest`

---

### Success

#### 201 Created

#### Percent Coupon

```
{
    "id":15,
    "type":"percent",
    "title":"전 메뉴 10% 할인",
    "sale_percent":10,
    "sale_max":5000,
    "target":"전 메뉴",
    "expiry_date":"2026-08-31T23:59:59Z"
}
```

#### Fixed Coupon

```
{
    "id":16,
    "type":"fixed",
    "title":"3,000원 할인",
    "sale_price":3000,
    "min_buy_price":15000,
    "coupon_num":100,
    "is_coupon_infinity":false,
    "expiry_date":"2026-09-30T23:59:59Z"
}
```

#### Stamp Policy

```
{
    "id":1,
    "type":"stamp",
    "goal":10,
    "reward":"아메리카노 1잔 무료",
    "condition":"결제 시 적립",
    "expiry_date":"2026-12-31T23:59:59Z"
}
```

---

### Error

#### 400 Bad Request

```
{
    "error":"invalid_request",
    "message":"잘못된 요청입니다."
}
```

#### 401 Unauthorized

```
{
    "error":"unauthorized",
    "message":"로그인이 필요합니다."
}
```

## GET /coupons

### Description

사장님이 현재 발급 중인 쿠폰 및 스탬프 정책을 조회한다.

### Authentication

Bearer JWT 필요

### Headers

| Name          | Type   | Required | Description  |
| ------------- | ------ | -------- | ------------ |
| Authorization | string | O        | Bearer <JWT> |

---

### Success

#### 200 OK

```python
[
    {
        "id": 1,
        "type": "percent",
        "sale_percent": 10,
        "sale_max": 5000,
        "is_apply_all": true,
        "expiry_date": "2026-08-31T23:59:59Z"
    },
    {
        "id": 2,
        "type": "stamp",
        "stamp_max_require": 10,
        "reward_content": "아메리카노 1잔 무료",
        "is_visit_stamp": false,
        "expiry_date": "2026-12-31T23:59:59Z"
    },
    {
        "id": 3,
        "type": "fixed",
        "sale_price": 3000,
        "min_buy_price": 15000,
        "coupon_num": 100,
        "is_coupon_infinity": false,
        "expiry_date": "2026-09-30T23:59:59Z"
    }
]
```

## DELETE /coupons/{id}

### Description

발급 중인 쿠폰 또는 스탬프 정책을 삭제한다.

### Authentication

Bearer JWT 필요

### Headers

| Name          | Type   | Required | Description  |
| ------------- | ------ | -------- | ------------ |
| Authorization | string | O        | Bearer <JWT> |

---

### Path Parameter

| Name | Type | Required | Description    |
| ---- | ---- | -------- | -------------- |
| id   | int  | O        | 삭제할 쿠폰 ID |

---

### Success

#### 204 No Content

응답 본문 없음.

---

### Error

#### 404 Not Found

```
{
    "error":"coupon_not_found",
    "message":"쿠폰을 찾을 수 없습니다."
}
```

# Shop API

## GET /shop

### Description

현재 등록된 상점 정보를 조회한다.

### Authentication

Bearer JWT 필요

### Headers

| Name          | Type   | Required | Description  |
| ------------- | ------ | -------- | ------------ |
| Authorization | string | O        | Bearer <JWT> |

---

## Response

### 200 OK

```
{
    "id":1,
    "name":"동네커피 유성점",
    "category":"cafe",
    "region":"대전광역시 유성구 온천2동",
    "business_hours":"매일 08:00 ~ 22:00"
}
```

---

## Error

### 401 Unauthorized

```
{
    "error":"unauthorized",
    "message":"로그인이 필요합니다."
}
```

### 404 Not Found

```
{
    "error":"shop_not_found",
    "message":"등록된 매장이 없습니다."
}
```

## /menus

### 메뉴 등록

POST /admin /menus

설명: 관리자가 QR 결제에 사용할 메뉴를 등록한다.

---

Request Body

```json
{
  "name": "아메리카노",
  "price": 4500
}
```

| FIeld | Type    | Description |
| ----- | ------- | ----------- |
| name  | String  | 메뉴 이름   |
| price | Integer | 메뉴 가격   |

Response

성공

201 Created

```json
{
  "menuId": 1,
  "name": "아메리카노",
  "price": 4500
}
```

실패

400 Bad Request

```json
{
  "message": "메뉴 이름 또는 가격이 없습니다."
}
```

### 메뉴 전체 조회

GET /admin /menus

설명: 등록된 모든 메뉴를 조회한다.

---

Response

성공

```json
[
  {
    "menuId": 1,
    "name": "아메리카노",
    "price": 4500
  },
  {
    "menuId": 2,
    "name": "카페라떼",
    "price": 5000
  }
]
```

### 메뉴 상세 조회

GET /admin /menus/{menuId}

설명: 특정 메뉴 정보를 조회한다.

PathVariable

| 이름   | 타입 |
| ------ | ---- |
| menuId | Long |

---

Response

200 OK

```json
{
  "menuId": 1,
  "name": "아메리카노",
  "price": 4500
}
```

### 메뉴 수정

PATCH /admin /menus/{menuId}

설명: 등록된 메뉴 정보를 수정한다.

---

Request Body

```json
{
  "name": "아이스 아메리카노",
  "price": 5000
}
```

Response

200 OK

```json
{
  "menuId": 1,
  "name": "아이스 아메리카노",
  "price": 5000
}
```

### 메뉴 삭제

DELETE /admin /menus/{menuId}

설명: 등록된 메뉴를 삭제한다.

---

Response

204 No content

## /qrs

### 메뉴 선택 QR 생성

POST /admin /qrs/menu

설명: 등록된 메뉴를 선택하여 결제 QR을 생성한다.

---

Request Body

```json
{
  "menuIds": [1, 2]
}
```

Field

| Field   | Type   |
| ------- | ------ |
| menuIds | Long[] |

Response

201 Created

```json
{
  "qrId": 10,
  "amount": 9500,
  "qrImage": "{qr_image_url}"
}
```

### 직접 금액 입력시 QR 생성

POST /admin /qrs/direct

설명: 메뉴 등록 없이 가격을 설정해 QR을 생성한다.

---

Request Body

```json
{
  "amount": 5000
}
```

Response

201 Created

```json
{
  "qrId": 11,
  "amount": 5000,
  "qrImage": "{qr_image_url}"
}
```

### QR 조회

GET /admin /qrs/{qrId}

설명: 생성된 QR 정보를 조회한다.

(결제 대기 화면)

---

Response

200 OK

```json
{
  "qrId": 10,
  "amount": 9500,
  "status": "WAITING",
  "qrImage": "qr_image_url"
}
```

QR 상태 Enum

```java
QR_STATUS

WAITING
PAID
EXPIRED
```

### QR 삭제

DELETE /admin /qrs/{qrId}

설명: 생성된 QR을 삭제한다

---

Response

204 No content

## /payments

### 결제 완료 확인

GET /admin /payments/{paymentId}

설명: QR 결제가 완료된 정보를 조회한다.

---

Response

200 OK

```json
{
  "paymentId": 100,
  "amount": 9500,
  "status": "SUCCESS"
}
```

결제 상태

```java
PAYMENT_STATUS

WAITING
SUCCESS
FAILED
```

## /stamps

### 스탬프 적립 정보 조회

GET /admin /stamps/{stampId}

설명: 결제 완료 후 적립되는 스탬프 정보를 조회한다.

---

Response

```json
{
  "shopName": "동네카페",
  "currentStamp": 4,
  "maxStamp": 5
}
```
