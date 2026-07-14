# 유성으로 (Starway) — API 명세서 (상세)

> 개발용 실전 명세. 각 필드의 **데이터 타입**, **enum 값별 조건부 필드**(어떤 상태일 때 어떤 값이 함께/비어 들어가는지), **케이스별 실제 JSON 예시**까지 포함.
>
> 표기 규칙
> - `string` `int` `float` `bool` `datetime`(ISO8601) `null`
> - `A | null` → 조건에 따라 값이 있거나 null
> - `enum(a, b, c)` → 정해진 값 중 하나만
> - `?` → 특정 조건에서만 존재하는 필드 (없을 수도 있음)

---

## 0. 공통 규약

### 인증
데모용: 헤더 `X-User-Id: <int>` (해커톤 간소화). 운영 전환 시 `Authorization: Bearer <jwt>`.

### 공통 에러 응답
모든 4xx/5xx는 아래 형식으로 통일.
```json
{
  "error": "already_stamped_today",
  "message": "오늘은 이미 적립했어요"
}
```
| 필드 | 타입 | 설명 |
|---|---|---|
| error | string | 기계용 에러 코드 (snake_case) |
| message | string | 사람이 읽는 안내문 (그대로 화면 토스트에 사용 가능) |

### 날짜/시간
- 서버 응답은 항상 ISO8601 UTC: `"2025-07-13T14:20:00Z"`
- `d_day`(int)는 서버가 계산해 내려줌. 예: 12 → "D-12". 당일이면 0, 지났으면 음수.

---

## 1. Enum 정의 (한 곳에 모음)

개발 중 헷갈리기 쉬우니 값과 의미를 고정한다.

### coupon.type
| 값 | 의미 | 함께 해석되는 필드 |
|---|---|---|
| `discount_rate` | 정률 할인 | `value`는 퍼센트 (10 → 10%) |
| `discount_amount` | 정액 할인 | `value`는 원 (1000 → 1,000원) |
| `time_limited` | 시간 한정 | `value`는 사용 가능 시간(시). `time_limit_hours` 참고 |

### user_coupon.status
| 값 | 의미 | `used_at` | `expired_at` | 화면 CTA |
|---|---|---|---|---|
| `active` | 보유 중 (사용 가능) | `null` | `null` | "QR 스캔하러 가기" (활성) |
| `used` | 사용 완료 | **datetime** | `null` | "사용 완료된 쿠폰" (비활성) |
| `expired` | 기간 만료 | `null` | **datetime** | "기간 만료" (비활성) |

> 핵심: `status`에 따라 `used_at` / `expired_at` 중 하나만 값이 차고 나머지는 `null`. `active`면 둘 다 `null`.

### store.category
`enum("카페", "음식점", "뷰티", "기타")` — 필터 탭과 1:1 대응.

### user.role
`enum("customer", "owner")`

---

## 2. 데이터 모델 (타입 명시)

### User
```
id                    int
nickname              string
region                string          // "유성구 온천2동"
role                  enum(customer, owner)
created_at            datetime
```

### Store
```
id                    int
name                  string          // "동네커피 유성점"
category              enum(카페, 음식점, 뷰티, 기타)
region                string
business_hours        string          // "매일 08:00-22:00"
owner_id              int             // FK → User
```

### StampPolicy  (매장당 1개)
```
id                    int
store_id              int             // FK → Store
goal                  int             // 5
reward                string          // "아메리카노 1잔 무료"
condition             string          // "1일 1회·결제 시"
```

### StampCard  (손님 × 매장별 적립 현황)
```
id                    int
user_id               int             // FK → User
store_id              int             // FK → Store
current               int             // 3
updated_at            datetime        // 1일 1회 판정용 (마지막 적립 시각)
```

### Coupon  (매장이 발급 중인 원본)
```
id                    int
store_id              int             // FK → Store
type                  enum(discount_rate, discount_amount, time_limited)
title                 string          // "전 메뉴 10% 할인"
value                 int             // 10 | 1000 | (time_limited면 시간)
target                string          // "전 메뉴"
valid_until           datetime | null // time_limited는 발급 후 상대시간이라 null 가능
time_limit_hours      int | null      // type == time_limited 일 때만 값 (예: 2), 아니면 null
store_only            bool            // 발급 매장에서만 사용 가능
```

### UserCoupon  (손님이 받은 쿠폰)
```
id                    int
user_id               int             // FK → User
coupon_id             int             // FK → Coupon
status                enum(active, used, expired)
claimed_at            datetime        // 받은 시각
used_at               datetime | null // status==used 일 때만 값
expired_at            datetime | null // status==expired 일 때만 값
```

---

## 3. 엔드포인트 (타입 + 케이스별 예시)

---

### 3-1. `GET /stores` — 매장 목록

**Query Parameters**
| 이름 | 타입 | 필수 | 기본 | 설명 |
|---|---|---|---|---|
| region | string | N | 사용자 기본 지역 | "유성구 온천2동" |
| category | enum(카페,음식점,뷰티,기타,all) | N | all | 업종 필터 |
| sort | enum(popular, recent) | N | popular | 정렬 |

**200 응답**
```json
{
  "stores": [
    {
      "id": 1,
      "name": "동네커피 유성점",
      "category": "카페",
      "region": "유성구 온천2동",
      "stamp_summary": { "current": 3, "goal": 5 }
    }
  ]
}
```

응답 필드 타입:
```
stores[].id                     int
stores[].name                   string
stores[].category               enum(카페, 음식점, 뷰티, 기타)
stores[].region                 string
stores[].stamp_summary          object | null   // 아직 적립 이력 없으면 null
stores[].stamp_summary.current  int
stores[].stamp_summary.goal     int
```

**케이스: 아직 이 매장에서 적립한 적 없음** → `stamp_summary`는 `null` (Image 4의 "0/5" 대신 아예 시작 전이면 null, 프론트가 "첫 스탬프 찍으면 시작"으로 표시)
```json
{ "id": 2, "name": "우리분식", "category": "음식점", "region": "유성구 온천2동", "stamp_summary": null }
```

---

### 3-2. `GET /stores/{store_id}` — 매장 상세

**Path**: `store_id` (int)

**200 응답**
```json
{
  "id": 1,
  "name": "동네커피 유성점",
  "category": "카페",
  "region": "유성구 온천2동",
  "business_hours": "매일 08:00-22:00",
  "stamp": {
    "goal": 5,
    "current": 3,
    "reward": "아메리카노 1잔 무료",
    "condition": "1일 1회·결제 시",
    "stamped_today": false
  }
}
```

응답 필드 타입:
```
id                     int
name                   string
category               enum(카페, 음식점, 뷰티, 기타)
region                 string
business_hours         string
stamp.goal             int
stamp.current          int
stamp.reward           string
stamp.condition        string
stamp.stamped_today    bool        // 오늘 이미 적립했는지 (버튼 활성/비활성 판단)
```

**케이스 A — 적립 진행 중 (3/5, 오늘 아직 안 찍음)**: 위 예시.

**케이스 B — 목표 달성 (5/5)**
```json
{
  "id": 1, "name": "동네커피 유성점", "category": "카페",
  "region": "유성구 온천2동", "business_hours": "매일 08:00-22:00",
  "stamp": {
    "goal": 5, "current": 5,
    "reward": "아메리카노 1잔 무료",
    "condition": "1일 1회·결제 시",
    "stamped_today": true
  }
}
```

**404** — 존재하지 않는 매장
```json
{ "error": "store_not_found", "message": "매장을 찾을 수 없어요" }
```

---

### 3-3. `GET /coupons` — 쿠폰 탐색

**Query Parameters**
| 이름 | 타입 | 필수 | 기본 |
|---|---|---|---|
| region | string | N | 사용자 기본 지역 |
| category | enum(카페,음식점,뷰티,기타,all) | N | all |
| sort | enum(popular, recent) | N | popular |

**200 응답 — 여러 타입이 섞여 나오는 예시**
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
      "valid_until": "2025-07-25T23:59:59Z",
      "d_day": 12,
      "time_limit_hours": null,
      "store_only": true,
      "claimed_by_me": false
    },
    {
      "id": 11,
      "store_name": "아삭샐러드",
      "type": "discount_amount",
      "title": "1,000원 할인",
      "value": 1000,
      "target": "전 메뉴",
      "valid_until": "2025-07-20T23:59:59Z",
      "d_day": 7,
      "time_limit_hours": null,
      "store_only": true,
      "claimed_by_me": false
    },
    {
      "id": 12,
      "store_name": "아씨꽃방",
      "type": "time_limited",
      "title": "2시간 내 사용",
      "value": 2,
      "target": "전 상품",
      "valid_until": null,
      "d_day": null,
      "time_limit_hours": 2,
      "store_only": true,
      "claimed_by_me": false
    }
  ]
}
```

응답 필드 타입 (type별 조건부에 주의):
```
coupons[].id                 int
coupons[].store_name         string
coupons[].type               enum(discount_rate, discount_amount, time_limited)
coupons[].title              string
coupons[].value              int          // %(rate) | 원(amount) | 시간(time_limited)
coupons[].target             string
coupons[].valid_until        datetime | null   // time_limited면 null
coupons[].d_day              int | null        // time_limited면 null (받은 뒤부터 카운트)
coupons[].time_limit_hours   int | null        // type==time_limited 일 때만 값
coupons[].store_only         bool
coupons[].claimed_by_me      bool         // true면 "받기"→"보유 중" 비활성
```

> **type별 규칙 요약**
> - `discount_rate` / `discount_amount`: `valid_until`·`d_day` 값 있음, `time_limit_hours` = null
> - `time_limited`: `valid_until`·`d_day` = null, `time_limit_hours` 값 있음

---

### 3-4. `POST /coupons/{coupon_id}/claim` — 쿠폰 받기

**Path**: `coupon_id` (int) · **Body**: 없음

**201 응답**
```json
{
  "user_coupon_id": 55,
  "coupon_id": 10,
  "status": "active",
  "claimed_at": "2025-07-13T14:20:00Z",
  "message": "쿠폰함에 담겼어요"
}
```
```
user_coupon_id   int
coupon_id        int
status           enum(active)      // 갓 받았으니 항상 active
claimed_at       datetime
message          string
```

**409 — 이미 받은 쿠폰**
```json
{ "error": "already_claimed", "message": "이미 받은 쿠폰이에요" }
```

**410 — 발급 마감/만료된 쿠폰**
```json
{ "error": "coupon_expired", "message": "발급이 종료된 쿠폰이에요" }
```

---

### 3-5. `GET /me/coupons` — 내 보유 쿠폰

**Query**
| 이름 | 타입 | 필수 | 기본 | 설명 |
|---|---|---|---|---|
| status | enum(active, used, expired, all) | N | active | 상태 필터 |

**200 응답 — status별로 다른 필드가 채워지는 예시**
```json
{
  "coupons": [
    {
      "user_coupon_id": 55,
      "store_name": "우리분식",
      "type": "discount_rate",
      "title": "전 메뉴 10% 할인",
      "value": 10,
      "status": "active",
      "claimed_at": "2025-07-13T14:20:00Z",
      "used_at": null,
      "expired_at": null,
      "valid_until": "2025-07-25T23:59:59Z",
      "d_day": 12
    },
    {
      "user_coupon_id": 42,
      "store_name": "우리분식",
      "type": "discount_rate",
      "title": "전 메뉴 10% 할인",
      "value": 10,
      "status": "used",
      "claimed_at": "2025-07-01T10:00:00Z",
      "used_at": "2025-07-02T12:30:00Z",
      "expired_at": null,
      "valid_until": "2025-07-25T23:59:59Z",
      "d_day": 12
    },
    {
      "user_coupon_id": 30,
      "store_name": "우리분식",
      "type": "discount_rate",
      "title": "전 메뉴 10% 할인",
      "value": 10,
      "status": "expired",
      "claimed_at": "2025-06-01T10:00:00Z",
      "used_at": null,
      "expired_at": "2025-06-30T23:59:59Z",
      "valid_until": "2025-06-30T23:59:59Z",
      "d_day": -13
    }
  ]
}
```

응답 필드 타입 (status에 따라 조건부):
```
user_coupon_id   int
store_name       string
type             enum(discount_rate, discount_amount, time_limited)
title            string
value            int
status           enum(active, used, expired)
claimed_at       datetime
used_at          datetime | null    // status==used 일 때만 값, 그 외 null
expired_at       datetime | null    // status==expired 일 때만 값, 그 외 null
valid_until      datetime | null    // time_limited면 null
d_day            int | null
```

> **status별 채워지는 값 (한눈에)**
> | status | used_at | expired_at | 화면 표시 |
> |---|---|---|---|
> | active | null | null | 사용 가능, "QR 스캔하러 가기" |
> | used | **값** | null | "사용완료" 스탬프 + CTA 비활성 |
> | expired | null | **값** | "만료" + CTA 비활성 |

**케이스 — 보유 쿠폰 0개** (Image 5 빈 상태)
```json
{ "coupons": [] }
```

---

### 3-6. `GET /me/coupons/{user_coupon_id}` — 보유 쿠폰 상세

**Path**: `user_coupon_id` (int)

**200 — active**
```json
{
  "user_coupon_id": 55,
  "store": { "name": "우리분식", "category": "음식점", "region": "유성구 온천2동", "business_hours": "매일 10:00-21:00" },
  "type": "discount_rate",
  "title": "전 메뉴 10% 할인",
  "value": 10,
  "target": "전 메뉴",
  "status": "active",
  "used_at": null,
  "expired_at": null,
  "valid_until": "2025-07-25T23:59:59Z",
  "d_day": 12,
  "store_only": true,
  "usage_note": "발급 매장에서만 사용 가능"
}
```

**200 — used** (Image 2: "사용완료" 도장)
```json
{
  "user_coupon_id": 42,
  "store": { "name": "우리분식", "category": "음식점", "region": "유성구 온천2동", "business_hours": "매일 10:00-21:00" },
  "type": "discount_rate", "title": "전 메뉴 10% 할인", "value": 10, "target": "전 메뉴",
  "status": "used",
  "used_at": "2025-07-02T12:30:00Z",
  "expired_at": null,
  "valid_until": "2025-07-25T23:59:59Z",
  "d_day": 12,
  "store_only": true,
  "usage_note": "발급 매장에서만 사용 가능"
}
```

**200 — expired** (Image 2: "기간 만료")
```json
{
  "user_coupon_id": 30,
  "store": { "name": "우리분식", "category": "음식점", "region": "유성구 온천2동", "business_hours": "매일 10:00-21:00" },
  "type": "discount_rate", "title": "전 메뉴 10% 할인", "value": 10, "target": "전 메뉴",
  "status": "expired",
  "used_at": null,
  "expired_at": "2025-06-30T23:59:59Z",
  "valid_until": "2025-06-30T23:59:59Z",
  "d_day": -13,
  "store_only": true,
  "usage_note": "발급 매장에서만 사용 가능"
}
```

---

### 3-7. `POST /stamps` — 스탬프 적립 ⭐ 핵심

결제 확인 후, 사장님 앱이 손님 QR을 스캔해서 호출.

**Body**
```json
{
  "store_id": 1,
  "customer_token": "eyJ1c2VyIjoxMDB9"
}
```
```
store_id          int       (필수)
customer_token    string    (필수)  // 손님 QR에 담긴 식별 토큰
```

**200 — 적립 성공 (아직 목표 전)**
```json
{
  "store_name": "동네커피 유성점",
  "current": 4,
  "goal": 5,
  "reward_reached": false,
  "reward": null,
  "message": "스탬프 1개 적립됐어요"
}
```

**200 — 적립으로 목표 달성**
```json
{
  "store_name": "동네커피 유성점",
  "current": 5,
  "goal": 5,
  "reward_reached": true,
  "reward": "아메리카노 1잔 무료",
  "message": "5개 완성! 아메리카노 1잔 무료예요"
}
```

응답 필드 타입:
```
store_name        string
current           int
goal              int
reward_reached    bool
reward            string | null    // reward_reached==true 일 때만 값, 아니면 null
message           string
```

**409 — 오늘 이미 적립** (조건: 1일 1회)
```json
{ "error": "already_stamped_today", "message": "오늘은 이미 적립했어요" }
```

**400 — 무효/만료 QR** (Image 1 마지막 화면)
```json
{ "error": "invalid_qr", "message": "유효하지 않은 QR이에요" }
```

---

### 3-8. `POST /me/coupons/{user_coupon_id}/use` — 쿠폰 사용

결제 시 쿠폰 적용. (사장님이 손님 QR 스캔 → 결제 화면)

**200 — 사용 성공**
```json
{
  "user_coupon_id": 55,
  "status": "used",
  "used_at": "2025-07-13T14:20:00Z",
  "message": "쿠폰이 사용되었어요"
}
```
```
user_coupon_id   int
status           enum(used)
used_at          datetime
message          string
```

**409 — 이미 사용됨**
```json
{ "error": "already_used", "message": "이미 사용된 쿠폰이에요", "used_at": "2025-07-02T12:30:00Z" }
```

**410 — 만료됨**
```json
{ "error": "coupon_expired", "message": "기간이 만료된 쿠폰이에요", "expired_at": "2025-06-30T23:59:59Z" }
```

---

### 3-9. `GET /me` — 내 정보

**200 응답**
```json
{
  "id": 100,
  "nickname": "홍길동",
  "region": "유성구 온천2동",
  "role": "customer",
  "unread_notifications": 6
}
```
```
id                     int
nickname               string
region                 string
role                   enum(customer, owner)
unread_notifications   int
```

---

## 4. 조건부 필드 규칙 총정리 (개발 중 자주 볼 표)

### user_coupon.status → used_at / expired_at
| status | used_at | expired_at |
|---|---|---|
| active | `null` | `null` |
| used | datetime | `null` |
| expired | `null` | datetime |

### coupon.type → value 단위 / valid_until / time_limit_hours
| type | value 의미 | valid_until | d_day | time_limit_hours |
|---|---|---|---|---|
| discount_rate | 퍼센트(%) | datetime | int | `null` |
| discount_amount | 금액(원) | datetime | int | `null` |
| time_limited | 시간(h) | `null` | `null` | int |

### stamps 응답 → reward
| reward_reached | reward |
|---|---|
| false | `null` |
| true | string (리워드명) |

---

## 5. 구현 우선순위 (해커톤)

1. ⭐ **스탬프 루프**: `GET /stores/{id}` → `POST /stamps` (409/400 케이스 포함)
2. **쿠폰 흐름**: `GET /coupons` → `POST /coupons/{id}/claim` → `GET /me/coupons`
3. **목록·프로필**: `GET /stores`, `GET /me`
4. 상세/사용: `GET /me/coupons/{id}`, `POST /me/coupons/{id}/use`

> 필드는 언제든 추가 가능. 지금은 화면이 요구하는 최소만, 부족하면 그때 붙인다.

---
---

# 📎 추가분 (신규 화면 반영)

> 로그인 · 패스 · 혜택선택 결제 · 인앱결제(데모) · 리워드 전환 · 이용내역 화면이 추가되어 아래 내용을 덧붙임.
> 위 기존 명세는 그대로 유효하고, 여기서는 **새로 필요한 것만** 정의한다.

---

## 6. 추가 Enum

### pass.scope (패스 사용 범위)
| 값 | 의미 | 화면 근거 |
|---|---|---|
| `store` | 특정 매장 전용 | — |
| `category` | 특정 업종 전 매장 (예: 카페 전 매장) | "주말 카페 패스 · 카페 결제 10% 할인" |
| `all` | 유성구 전 매장 | "올패스 · 모든 매장 10% 할인" |

### pass.period_type (패스 기간 유형)
| 값 | 의미 | 함께 들어가는 값 | 화면 근거 |
|---|---|---|---|
| `one_day` | 관광객용 1일권 (일정액) | `price` 있음, `duration_days`=1 | "유성 원데이 패스 · 1일권" |
| `period` | 주민용 기간권 (월정액 계열) | `price` 있음, `duration_days`=30 등 | "1일·30일" 범위 표기 |

### user_pass.status (보유 패스 상태)
| 값 | 의미 | `expires_at` | 화면 표시 |
|---|---|---|---|
| `active` | 사용 가능 | datetime | "D-24" 등 남은 기간 |
| `expired` | 기간 만료 | datetime (과거) | 비활성 |

### benefit.kind (결제 시 선택하는 혜택 종류) — Image 6
결제 화면에서 쿠폰과 패스를 **하나의 선택지 목록**으로 합쳐 보여주므로 통합 종류값이 필요.
| 값 | 의미 | 뱃지 표기 |
|---|---|---|
| `coupon_rate` | 정률 할인 쿠폰 | `PERCENT` |
| `coupon_amount` | 정액 할인 쿠폰 | `FIXED` |
| `pass` | 패스 | `PASS` |
| `none` | 사용 안 함 (원가 결제) | — |

### transaction.type (이용내역 종류) — Image 1
| 값 | 의미 | 금액 표기 |
|---|---|---|
| `pass_use` | 패스 사용 | `-1,800원` |
| `pass_purchase` | 패스 구매 | `9,900원` |
| `stamp_earn` | 스탬프 적립 | `+1 · 4/5` |
| `coupon_use` | 쿠폰 사용 | `-1,800원` |
| `coupon_claim` | 쿠폰 받기 | "10% 할인 구폰" |
| `reward_issue` | 리워드 쿠폰 발급 | "스탬프 5/5" |
| `coupon_expire` | 쿠폰 만료 | "1,000원 할인" |

---

## 7. 추가 데이터 모델

### Pass (패스 원본 — 마켓에 진열되는 상품)
화면 근거: 패스 마켓 카드 (Image 2)
```
id                int
name              string          // "주말 카페 패스"
scope             enum(store, category, all)
period_type       enum(one_day, period)
duration_days     int             // 1 | 30 ...
price             int             // 2900 | 9900 ... (원)
discount_rate     int             // 10 (%)
target_desc       string          // "카페 결제 · 유성구 전 매장"
usage_note        string          // "결제 시 사장님 QR 스캔하고 이 패스 선택"
```

### UserPass (손님이 구매한 패스)
```
id                int
user_id           int             // FK → User
pass_id           int             // FK → Pass
status            enum(active, expired)
purchased_at      datetime
expires_at        datetime        // D-day 계산용
```

### Transaction (이용내역 — 통합 타임라인)
화면 근거: 마이 > 이용내역 (Image 1). 위 여러 행동을 한 줄씩 시간순으로 기록.
```
id                int
user_id           int             // FK → User
type              enum(pass_use, pass_purchase, stamp_earn, coupon_use, coupon_claim, reward_issue, coupon_expire)
store_name        string | null   // 매장명 (해당 없으면 null)
amount            int | null      // 금액 변화 (음수=할인/사용, 양수=구매). 금액 없는 이벤트는 null
memo              string | null   // "+1 · 4/5", "10% 할인 쿠폰", "스탬프 5/5" 등 보조 텍스트
created_at        datetime        // 타임라인 정렬 기준
```

> StampPolicy에 필드 하나 추가 필요 — **min_payment**(최소 결제금액, 없으면 0)와 정률 쿠폰 상한(**max_discount**)이 결제 계산에 쓰임. Coupon 모델에도 아래 추가:
```
Coupon 추가 필드:
  min_payment       int      // 사용 최소 주문금액 (예: 5000). 미달 시 비활성 (Image 6 2번째 화면)
  max_discount      int | null   // 정률 쿠폰 상한 (예: 2000). discount_rate 타입에서만 의미, 그 외 null
```

---

## 8. 추가 엔드포인트

---

### 8-1. `POST /auth/google` — 로그인 (Image 7)
Google 소셜 로그인. 프론트가 받은 Google id_token을 서버에 전달.

**Body**
```json
{ "id_token": "google가 발급한 토큰" }
```
**200 — 기존 회원 / 신규 회원 자동 가입**
```json
{
  "user_id": 100,
  "nickname": "김온천",
  "role": "customer",
  "is_new": false,
  "access_token": "서버 세션 토큰"
}
```
```
user_id        int
nickname       string
role           enum(customer, owner)
is_new         bool         // true면 온보딩(지역 설정 등)으로
access_token   string
```
> "사장님이신가요? 가맹점 등록하기" 링크는 별도 플로우 → `role: owner`로 가입 유도.

---

### 8-2. `GET /passes` — 패스 마켓 (Image 2)
구매 가능한 패스 목록.

**Query**: `region`(string, N)

**200 응답**
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
      "target_desc": "관광지·카페·음식점 10% 할인",
      "owned": false
    },
    {
      "id": 2,
      "name": "주말 카페 패스",
      "scope": "category",
      "period_type": "period",
      "duration_days": 30,
      "price": 1500,
      "discount_rate": 10,
      "target_desc": "카페 결제 10% 할인",
      "owned": false
    }
  ]
}
```
```
passes[].id             int
passes[].name           string
passes[].scope          enum(store, category, all)
passes[].period_type    enum(one_day, period)
passes[].duration_days  int
passes[].price          int
passes[].discount_rate  int
passes[].target_desc    string
passes[].owned          bool     // true면 "구매하기"→"보유 중" 비활성 (Image 2 4번째)
```

---

### 8-3. `GET /passes/{pass_id}` — 패스 상세 (Image 2 마지막)
```json
{
  "id": 2,
  "name": "주말 카페 패스",
  "scope": "category",
  "discount_rate": 10,
  "target_desc": "카페 결제 · 유성구 전 매장",
  "price_options": [
    { "duration_days": 1, "price": 1500 },
    { "duration_days": 30, "price": 9900 }
  ],
  "usage_note": "결제 시 사장님의 결제 QR을 스캔하고 이 패스를 선택하면 할인이 적용돼요.",
  "notice": "할인 차액은 유성구청이 보전해요",
  "owned": false
}
```
> `price_options`는 배열 — "1일 1,500원 ~ 30일 9,900원"처럼 여러 기간 옵션을 한 패스에서 고르게 함.

---

### 8-4. `GET /me/passes` — 내 패스 (Image 2 "내 패스" 탭)
**Query**: `status`(enum active, expired, all / 기본 active)
```json
{
  "passes": [
    {
      "user_pass_id": 88,
      "name": "주말 카페 패스",
      "scope": "category",
      "discount_rate": 10,
      "status": "active",
      "expires_at": "2025-08-06T23:59:59Z",
      "d_day": 24
    }
  ]
}
```
> 빈 배열이면 "아직 보유한 패스가 없어요" (Image 2 2번째).

---

### 8-5. `POST /passes/{pass_id}/purchase` — 패스 구매
**Body**
```json
{ "duration_days": 30 }
```
**201 응답**
```json
{
  "user_pass_id": 88,
  "name": "주말 카페 패스",
  "status": "active",
  "expires_at": "2025-08-06T23:59:59Z",
  "paid": 9900,
  "message": "패스 구매가 완료됐어요"
}
```
> 이 호출은 Transaction에 `pass_purchase` 한 줄을 남긴다.

---

### 8-6. `GET /checkout/benefits` — 결제 시 사용 가능 혜택 조회 ⭐ (Image 6)
결제 QR 스캔 직후, **이 매장·이 주문금액에서 쓸 수 있는 쿠폰+패스를 한 목록으로** 내려주고 각 할인액을 실시간 계산해 준다.

**Query**
| 이름 | 타입 | 필수 | 설명 |
|---|---|---|---|
| store_id | int | Y | 결제 매장 |
| amount | int | Y | 주문금액 (예: 18000) |

**200 응답 — amount=18000 예시**
```json
{
  "store_name": "동네커피 유성점",
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
```
store_name              string
amount                  int
benefits[].benefit_id   string    // "coupon:{id}" | "pass:{id}" | "none"
benefits[].kind         enum(coupon_rate, coupon_amount, pass, none)
benefits[].title        string
benefits[].desc         string
benefits[].discount     int       // 이 혜택 적용 시 할인액 (서버가 계산: 상한·정률 반영)
benefits[].selectable   bool      // false면 비활성 (회색)
benefits[].reason       string | null  // 비활성 사유. selectable=false일 때만 값
```

**케이스 — 최소 결제금액 미달** (Image 6 2번째, amount=4000)
정액 1,000원 쿠폰이 "5,000원 이상" 조건이라 비활성:
```json
{
  "benefit_id": "coupon:60",
  "kind": "coupon_amount",
  "title": "1,000원 할인 쿠폰",
  "desc": "5,000원 이상 · 이 매장 발급분",
  "discount": 0,
  "selectable": false,
  "reason": "5,000원 이상부터 사용 가능"
}
```
> 정률 쿠폰도 amount가 작으면 할인액이 그만큼 작아짐 (4000의 10% = 400원).

**케이스 — 정률 상한 적용** (Image 6 3번째, amount=30000)
10%면 3,000원이지만 상한 2,000원이라 잘림:
```json
{
  "benefit_id": "coupon:55",
  "kind": "coupon_rate",
  "title": "10% 할인 쿠폰",
  "desc": "이 매장 발급분 · 최대 2,000원",
  "discount": 2000,
  "selectable": true,
  "reason": "최대 2,000원 적용"
}
```

**케이스 — 적용 가능 혜택 없음** (Image 6 4번째)
```json
{ "store_name": "동네커피 유성점", "amount": 18000, "benefits": [ { "benefit_id": "none", "kind": "none", "title": "사용 안함", "desc": "원가 그대로 결제", "discount": 0, "selectable": true, "reason": null } ] }
```

---

### 8-7. `POST /checkout` — 인앱 결제(데모) 실행 (Image 5)
선택한 혜택으로 최종 결제. 데모 결제라 실제 PG 없이 성공/실패만 시뮬레이션.

**Body**
```json
{
  "store_id": 1,
  "amount": 18000,
  "benefit_id": "coupon:55",
  "method": "easy_pay"
}
```
```
store_id      int
amount        int
benefit_id    string    // /checkout/benefits에서 고른 값. "none"이면 원가
method        enum(easy_pay, card)   // 간편결제 | 신용·체크카드 (둘 다 데모)
```

**200 — 결제 성공 (쿠폰 사용)**
```json
{
  "result": "success",
  "store_name": "우리분식",
  "benefit_applied": "10% 할인 쿠폰 (-1,800원)",
  "final_amount": 16200,
  "benefit_kind": "coupon_rate",
  "consumed": true,
  "message": "쿠폰이 사용 처리됐어요"
}
```
```
result           enum(success, fail)
store_name       string
benefit_applied  string | null   // 적용 혜택 설명, none이면 null
final_amount     int
benefit_kind     enum(coupon_rate, coupon_amount, pass, none)
consumed         bool     // 쿠폰=true(한 번 쓰면 사라짐), 패스=false(기록으로 남음)
message          string
```
> `benefit_kind`가 coupon이면 "한 번 쓰면 사라지는 소진형" 안내, pass면 "이용 기록으로 남아" 안내 (Image 5의 3·4번째 차이).
> 결제 성공 시 Transaction에 `coupon_use` 또는 `pass_use` 기록.

**200 — 결제 실패(데모)** (Image 5 마지막)
```json
{ "result": "fail", "message": "데모 결제 중 문제가 생겼어요. 다시 시도해 주세요." }
```

---

### 8-8. `POST /stamps` 갱신 — 결제금액·첫적립·리워드 전환 (Image 3·4)
기존 3-7 엔드포인트에 아래 사항을 반영/추가한다. **경로·요청은 동일**, 응답과 동작만 확장.

**요청에 결제금액 추가** (Image 4의 "오프라인 결제 금액 18,000원")
```json
{
  "store_id": 1,
  "customer_token": "...",
  "amount": 18000
}
```
> `amount`(int, N): 화면에 표시/기록용. 적립 조건이 "결제 시"이므로 참고값으로 받되, 스탬프 개수 자체는 방문 1회=1개 로직 유지.

**200 — 첫 적립 (카드 자동 생성)** (Image 4 3번째)
```json
{
  "store_name": "동네커피 유성점",
  "current": 1,
  "goal": 5,
  "reward_reached": false,
  "reward": null,
  "card_created": true,
  "message": "동네커피 유성점 스탬프가 시작됐어요"
}
```

**200 — 적립으로 5/5 도달 → 리워드 쿠폰 자동 발급 + 카드 리셋** (Image 3)
```json
{
  "store_name": "동네커피 유성점",
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
추가 응답 필드:
```
card_created       bool             // 이번 호출로 스탬프 카드가 새로 생겼는지
reward_coupon      object | null    // reward_reached==true 일 때만. 발급된 리워드 쿠폰 정보
reward_coupon.user_coupon_id  int
reward_coupon.title           string
reward_coupon.d_day           int
card_reset_to      int | null       // 리워드 발급 후 카드가 리셋된 값(0). 아니면 null
```
> 흐름: 5번째 적립 → 리워드 쿠폰이 UserCoupon으로 발급됨(쿠폰함에서 확인) → 같은 매장 StampCard.current를 0으로 초기화 → 다음 사이클 시작.

---

### 8-9. `GET /me/transactions` — 이용내역 (Image 1)
마이 탭. 쿠폰·스탬프·패스 활동을 하나의 타임라인으로.

**Query**
| 이름 | 타입 | 필수 | 기본 | 설명 |
|---|---|---|---|---|
| filter | enum(all, coupon, stamp, pass) | N | all | 상단 필터칩 |
| cursor | string | N | — | 페이지네이션 ("더보기"/스크롤) |

**200 응답**
```json
{
  "transactions": [
    { "id": 501, "type": "pass_use",     "store_name": "동네커피 유성점", "amount": -1800, "memo": null,          "created_at": "2026-07-13T14:20:00Z" },
    { "id": 500, "type": "stamp_earn",   "store_name": "동네커피 유성점", "amount": null,  "memo": "+1 · 4/5",    "created_at": "2026-07-13T14:20:00Z" },
    { "id": 480, "type": "coupon_use",   "store_name": "우리분식",       "amount": -1800, "memo": null,          "created_at": "2026-07-12T19:05:00Z" },
    { "id": 479, "type": "coupon_claim", "store_name": "우리분식",       "amount": null,  "memo": "10% 할인 쿠폰", "created_at": "2026-07-12T12:30:00Z" },
    { "id": 450, "type": "reward_issue", "store_name": "동네커피 유성점", "amount": null,  "memo": "스탬프 5/5",   "created_at": "2026-07-10T09:00:00Z" },
    { "id": 449, "type": "pass_purchase","store_name": null,            "amount": 9900,  "memo": "주말 카페 패스", "created_at": "2026-07-10T09:00:00Z" },
    { "id": 400, "type": "coupon_expire","store_name": "아삭샐러드",     "amount": null,  "memo": "1,000원 할인",  "created_at": "2026-07-09T00:00:00Z" }
  ],
  "next_cursor": "eyJvZmZzZXQiOjIwfQ=="
}
```
```
transactions[].id           int
transactions[].type         enum(pass_use, pass_purchase, stamp_earn, coupon_use, coupon_claim, reward_issue, coupon_expire)
transactions[].store_name   string | null
transactions[].amount       int | null    // 음수=사용/할인, 양수=구매, null=금액없는 이벤트
transactions[].memo         string | null
transactions[].created_at   datetime
next_cursor                 string | null  // null이면 마지막 페이지
```
> 빈 배열이면 "아직 이용내역이 없어요" (Image 1 3번째). 필터 결과 0건이면 "패스 이용내역이 없어요" 식 (Image 1 4번째).

---

## 9. 추가분 구현 우선순위

기존 스탬프 루프(1순위)는 그대로. 새 화면들은 아래 순으로:

1. **로그인** `POST /auth/google` — 앱 진입에 필수, 먼저.
2. **스탬프 리워드 전환** `POST /stamps` 확장 — 5/5→쿠폰→리셋. 데모 하이라이트라 중요.
3. **혜택선택 결제** `GET /checkout/benefits` → `POST /checkout` — 계산 로직이 이 앱의 기술적 볼거리. 여유되면 진짜로 구현.
4. **패스** `GET /passes` → `POST /passes/{id}/purchase` → `GET /me/passes`
5. **이용내역** `GET /me/transactions` — 위 액션들이 기록을 남기게만 해두면 자동으로 채워짐.

> ⚠️ 혜택 계산(8-6)은 상한·최소금액 때문에 살짝 까다로움. 시간 부족하면 discount를 서버가 아니라 프론트가 계산하고, 서버는 목록만 내려주는 것으로 축소해도 데모엔 지장 없음.

---
---

# 🔄 QR 방향 변경 (최종 확정: 가게가 QR을 띄우고 손님이 스캔)

> **중요 변경.** 사장님 앱 화면(QR 생성 → "소비자 스캔 대기 중")이 최종 확정되면서 QR 방향이 뒤집혔다.
> 기존 3-7·8-7·8-8은 "손님이 QR 띄우고 가게가 스캔"(`customer_token`) 전제였는데, 이제 **가게가 QR을 생성·표시하고 손님이 스캔**한다.
> 아래가 최종 규격이며, 충돌 시 이 섹션이 위 내용보다 우선한다.

## 10. 새 흐름 요약

```
[사장님 앱]  QR 생성 (type=stamp 또는 payment)
             → 서버가 1회용 qr_token 발급 → 화면에 QR 표시 → "소비자 스캔 대기 중"
[손님 앱]    QR 스캔 → qr_token을 서버에 제출
[서버]       qr_token 검증(유효/미사용/만료) → 스탬프 적립 또는 결제 처리 → 양쪽에 결과
```

핵심 변화:
- **식별 주체가 뒤집힘.** 이제 QR은 손님이 아니라 **가게가 만든 1회용 토큰**을 담는다. 손님 식별은 스캔하는 손님의 `X-User-Id`(로그인)로 처리.
- **금액이 QR 생성 시점에 이미 정해짐.** 사장님이 결제 QR 만들 때 금액(직접 입력 or 메뉴 선택 합계)을 넣으므로, 손님이 스캔하면 그 금액이 따라온다.
- **1회용.** QR은 한 번 스캔되면 소진. 재스캔은 `already_used`.

## 11. 새 데이터 모델

### QrToken (가게가 생성하는 1회용 QR)
```
id              int
token           string          // QR에 담기는 값 (UUID 등, 추측 불가하게)
store_id        int             // FK → Store, 어느 가게가 만들었나
type            enum(stamp, payment)
amount          int | null      // type==payment면 금액, stamp면 null
status          enum(waiting, consumed, expired)  // 대기중 / 사용됨 / 만료
created_at      datetime
consumed_at     datetime | null // 스캔되어 처리된 시각
consumed_by     int | null      // 스캔한 손님 user_id
```
> 만료: 생성 후 일정 시간(예: 3~5분) 지나면 `expired`. 데모에선 만료 로직 생략하고 `consumed`만 관리해도 됨.

### Menu (메뉴 등록 — 결제 QR의 "메뉴 선택"용) — Image 3
```
id              int
store_id        int             // FK → Store
name            string          // "아메리카노"
price           int             // 4500
```

### StampPolicy 필드 추가 — Image 5 "적립 단위" 토글
```
earn_unit       enum(visit, payment)   // "방문 1회 +1" 또는 "결제 시 +1". 사장님이 선택.
```
> 이 프로젝트에서 계속 고민했던 "방문이냐 결제냐"의 최종 답: **사장님이 가게별로 선택**. 기본값 payment 권장.

## 12. 새/수정 엔드포인트 (가게 QR 생성 기준)

---

### 12-1. `POST /owner/qr` — 사장님이 QR 생성 (Image 2)
사장님 앱에서 QR을 만든다. 이 호출의 사용자는 **사장님**(`X-User-Id` = owner).

**Body — 스탬프 QR**
```json
{ "type": "stamp" }
```
**Body — 결제 QR (직접 입력)**
```json
{ "type": "payment", "amount": 4500 }
```
**Body — 결제 QR (메뉴 선택 합계)**
```json
{ "type": "payment", "menu_ids": [1, 2] }
```
```
type       enum(stamp, payment)   (필수)
amount     int | null    // 직접 입력 시. type==payment에서 필수(단, menu_ids로 대체 가능)
menu_ids   int[] | null  // 메뉴 선택 시. 서버가 합계를 계산해 amount로
```

**201 응답**
```json
{
  "qr_token": "b7f3c1a2-9e4d-4c8a-a1b2-5f6e7d8c9a0b",
  "type": "payment",
  "amount": 4500,
  "status": "waiting",
  "message": "소비자 스캔 대기 중"
}
```
```
qr_token   string     // 이 값을 QR 이미지로 렌더링
type       enum(stamp, payment)
amount     int | null
status     enum(waiting)
```
> 메뉴가 없는데 "메뉴 선택"을 누르면 `400 no_menu` → 화면 "먼저 메뉴를 등록하세요" (Image 2 4번째).

---

### 12-2. `GET /owner/qr/{qr_token}` — QR 상태 폴링 (선택)
사장님 화면이 "손님이 스캔했나?"를 확인. 손님이 스캔·처리하면 status가 바뀜.
```json
{ "qr_token": "...", "status": "consumed", "result_summary": "스탬프 4/5 적립" }
```
```
status          enum(waiting, consumed, expired)
result_summary  string | null   // 처리 결과 한 줄 (사장님 화면 "처리 완료"용)
```
> 데모에선 폴링 대신, 손님이 스캔 처리한 뒤 사장님이 "새 QR 만들기"를 누르는 것으로 단순화해도 됨 (Image 2 마지막).

---

### 12-3. `POST /scan` — 손님이 QR 스캔 (통합 진입점) ⭐ 핵심
손님 앱이 스캔한 `qr_token`을 제출. 이 호출의 사용자는 **손님**(`X-User-Id` = customer).
서버가 토큰의 type을 보고 스탬프 적립 또는 결제 준비로 분기한다. (기존 `POST /stamps`를 대체)

**Body**
```json
{ "qr_token": "b7f3c1a2-9e4d-4c8a-a1b2-5f6e7d8c9a0b" }
```

**200 — type이 stamp인 경우 → 즉시 적립** (Image 1 왼쪽 "스탬프 1개 적립 완료")
```json
{
  "kind": "stamp",
  "store_name": "동네커피 유성점",
  "amount": 18000,
  "current": 4,
  "goal": 5,
  "reward_reached": false,
  "reward": null,
  "card_created": false,
  "message": "스탬프 1개 적립 완료"
}
```
> `earn_unit`이 payment인 가게인데 이 스탬프 QR에 금액이 실려 있으면 `amount`도 함께 표시(Image 1은 결제금액 18,000 + 적립 4/5를 같이 보여줌). 5/5 도달·첫적립·리셋 로직은 기존 8-8과 동일(`reward_coupon`, `card_reset_to` 필드 그대로).

**200 — type이 payment인 경우 → 혜택 선택 단계로** (Image 2 결제 흐름 → 혜택 선택)
```json
{
  "kind": "payment",
  "store_id": 1,
  "store_name": "동네커피 유성점",
  "amount": 18000,
  "checkout_ready": true
}
```
> 이후 손님 앱은 이 `store_id`·`amount`로 `GET /checkout/benefits`(8-6)를 호출해 혜택을 고르고 `POST /checkout`(8-7)으로 결제. 8-6·8-7은 그대로 사용하되, amount를 손님이 아니라 **QR에서 받은 값**으로 넘긴다.

**에러**
```json
{ "error": "already_used", "message": "이미 처리된 QR이에요" }      // 409, Image 4의 "이미 처리된 QR"
{ "error": "qr_expired",  "message": "만료된 QR이에요. 새 QR로 다시 시도해 주세요" }  // 410
{ "error": "invalid_qr",  "message": "유효하지 않은 QR이에요" }     // 400
{ "error": "already_stamped_today", "message": "오늘은 이미 적립했어요" }  // 409, stamp 한정
```

---

### 12-4. 메뉴 CRUD — Image 3
결제 QR "메뉴 선택"과 사장님 메뉴 등록 화면용.
```
GET    /owner/menus              // 등록된 메뉴 목록
POST   /owner/menus              // { "name": "아인슈페너", "price": 6000 } → 201
PUT    /owner/menus/{menu_id}    // 수정
DELETE /owner/menus/{menu_id}    // 삭제
```
> 가격 미입력 시 `400 price_required` → "가격을 입력해주세요" (Image 3 3번째).

---

### 12-5. `POST /owner/coupons` — 사장님 쿠폰 발급 — Image 4·5
라이브 프리뷰가 있는 그 화면. 사장님이 만든 쿠폰이 Coupon 원본으로 등록됨.

**Body — 정률(PERCENT)**
```json
{
  "type": "discount_rate",
  "value": 10,
  "max_discount": 2000,
  "target": "전 메뉴",
  "valid_type": "date",
  "valid_days": 30,
  "issue_limit": null
}
```
**Body — 정액(FIXED)**
```json
{ "type": "discount_amount", "value": 1000, "min_payment": 5000, "target": "전 메뉴", "valid_type": "date", "valid_days": 30, "issue_limit": 50 }
```
**Body — 스탬프(STAMP)**
```json
{ "type": "stamp", "goal": 10, "reward": "아메리카노 1잔 무료", "earn_unit": "payment", "valid_type": "date", "valid_days": 30 }
```
```
type          enum(discount_rate, discount_amount, stamp)
value         int | null      // rate=%, amount=원. stamp면 null
max_discount  int | null      // 정률 상한 (선택)
min_payment   int | null      // 정액 최소결제 (선택)
goal          int | null      // stamp 목표 개수
reward        string | null   // stamp 리워드
earn_unit     enum(visit, payment) | null  // stamp 적립 단위
target        string          // "전 메뉴" | "특정 메뉴"
valid_type    enum(date, time)             // 날짜 | 시간
valid_days    int | null      // valid_type==date
valid_hours   int | null      // valid_type==time (예: 2시간)
issue_limit   int | null      // 발급 수량. null이면 무제한
```
**유효성 (Image 4·5의 에러들)**
```json
{ "error": "invalid_rate",  "message": "할인율은 1~99% 사이여야 해요" }   // 150% 입력 시
{ "error": "invalid_time",  "message": "유효 시간을 입력해주세요" }        // 0시간 입력 시
```

**201 응답**: 발급된 Coupon 반환 → "쿠폰이 발급됐어요" (Image 4).

---

### 12-6. `GET /owner/home` — 사장님 대시보드 — Image 6
```json
{
  "store_name": "동네커피 유성점",
  "approval_status": "approved",
  "business_hours": "10:00 - 21:00",
  "active_coupons": [
    { "coupon_id": 10, "title": "전 메뉴 10% 할인", "type": "discount_rate", "value": 10, "d_day": 12, "remaining": 84, "issue_limit": 100 }
  ],
  "today_summary": { "stamps": 12, "coupon_uses": 5 }
}
```
```
approval_status   enum(pending, approved)   // 심사중/승인. pending이면 액션 비활성 (Image 6 2번째)
active_coupons[].remaining      int | null   // 남은 발급 수량 (84/100)
today_summary.stamps            int          // 오늘 적립 건수
today_summary.coupon_uses       int          // 오늘 쿠폰 사용 건수
```
> `today_summary`가 곧 "통계의 씨앗". 발표에서 확장 로드맵으로 언급 가능.

---

### 12-7. `POST /owner/register` — 가맹점 등록 — Image 7
```json
{
  "name": "동네커피 유성점",
  "business_number": "123-45-67890",
  "category": "카페",
  "region": "유성구 온천2동",
  "business_hours": "10:00 - 21:00",
  "contact": "010-1234-5678"
}
```
**201 응답**
```json
{ "store_id": 1, "approval_status": "pending", "message": "심사가 접수됐어요" }
```
> 데모에선 자동 승인(즉시 approved)으로 처리해 흐름을 끊지 않는 걸 권장. 필수값 미입력은 각 필드 `400`.

## 13. 변경 요약 (기존 → 최종)

| 기존 (손님이 QR 띄움) | 최종 (가게가 QR 띄움) |
|---|---|
| `POST /stamps` + `customer_token` | `POST /owner/qr`로 QR 생성 → `POST /scan`으로 손님이 처리 |
| 손님 QR에 손님 식별값 | 가게 QR에 1회용 `qr_token`, 손님은 `X-User-Id`로 식별 |
| 결제 금액을 손님/사장이 별도 입력 | QR 생성 시 금액 확정 → 스캔 시 자동 전달 |
| — | QrToken, Menu 모델 추가, StampPolicy.earn_unit 추가 |

---
---

# ✅ 실제 구현 (hotfix 브랜치) — 위 §10~13 대비 반영/보류 내역

> 이 문서가 작성된 뒤 `main`에는 이미 매장 사장님용 `/admin/*` self-service API(메뉴, 쿠폰 발급, 결제 QR)와
> 구청 관리자용 `/admin/*` API(`web/` 패키지, JWT 인증)가 별도로 구현·병합되어 있었다. 그 기존 자산을
> 갈아엎지 않고 "QR 방향 전환"에 필요한 조각만 그 위에 얹는 쪽으로 구현했다. §10~13과 달라진 점을 명시한다.

## 실제 경로 (§10~13의 `/owner/*` 대신 기존 `/admin/*` 패턴을 따름)

| §12 계획 | 실제 구현 | 비고 |
|---|---|---|
| `POST /owner/qr` (type으로 stamp/payment 분기) | **`POST /admin/qrs/stamp`**(신규) + 기존 `POST /admin/qrs/direct`, `POST /admin/qrs/menu`(변경 없음, payment 타입 그대로) | 이미 `/admin/qrs/*` 하위에 결제 QR 생성 엔드포인트 2개가 있어서, 그 옆에 스탬프용 하나만 추가했다. `/owner/*`를 새로 파면 `/admin`(사장님)·`/admin`(구청, `web/`)에 이어 세 번째 prefix가 생겨 더 혼란스러워진다고 판단 |
| `GET /owner/qr/{qr_token}` (선택 사항) | **`GET /admin/qrs/{qr_id}`**(기존 엔드포인트 그대로 폴링 용도 겸용) | §12-2가 "선택"이라고 명시했고, 기존 엔드포인트가 이미 `status`를 반환해서 그대로 재사용. 응답에 `token`/`type` 필드만 추가 |
| `POST /scan` | **`POST /scan`** (신규, 경로 그대로) | 손님 인증은 `X-User-Id`(`require_user_id`) 그대로 사용 |
| `POST /owner/menus` 등 메뉴 CRUD | 손대지 않음 — 기존 `POST/GET/PATCH/DELETE /admin/menus[...]`가 이미 동작 중 | §12-4는 `PUT`을 제안하지만 기존 구현은 `PATCH`. 이번 hotfix 범위 밖이라 유지 |
| `POST /owner/coupons` | 손대지 않음 — 기존 `POST /admin/coupons`(percent/fixed/stamp 판별 유니온)가 이미 동작 중 | 필드명이 §12-5와 다르지만(예: `sale_percent` vs `value`), QR 방향과 무관한 별개 기능이라 이번 범위에서 제외 |
| `GET /owner/home`, `POST /owner/register` | 미구현 | `POST /admin/register`(사장님 self-service 매장 등록)가 이미 있어 register는 사실상 커버됨. 대시보드(`owner/home`)는 새 기능이라 범위 밖 |
| `QrToken` 신규 모델 | **기존 `PaymentQr` 모델을 확장**(`token`, `type`, `consumed_at`, `consumed_by` 컬럼 추가, `amount` nullable화) | 이미 있던 결제 QR 테이블과 개념이 겹쳐서 별도 테이블을 새로 만들지 않고 확장했다 |
| `Menu` 신규 모델 | 이미 존재(`app/models.py`) — 변경 없음 | |
| `status` enum `waiting/consumed/expired` | **`WAITING`/`CONSUMED`** (대문자 유지, `expired` 미구현) | 기존 `PaymentQr.status`가 이미 대문자 `"WAITING"`으로 테스트(`test_admin.py`)에 고정돼 있어서, casing을 바꾸면 기존 테스트가 깨진다. 만료 로직은 §10 문서 자체가 "데모에선 생략해도 됨"이라고 명시해 구현하지 않았다 |
| `StampPolicy.earn_unit`(visit/payment) | 미구현 | QR 방향 전환과는 별개의 정책(적립 단위) 변경이라 이번 hotfix 범위에서 제외. 필요하면 별도로 요청 바람 |

## `POST /scan` 실제 동작

```json
{ "qr_token": "3f9c1e2a7b4d4c1e9f0a2b3c4d5e6f7a" }
```
- 인증: `X-User-Id` 필수(`require_user_id`) — 스캔하는 손님을 식별.
- `qr_token`으로 `PaymentQr`를 조회. 없으면 `400 invalid_qr`. `status != WAITING`이면 `409 already_used`(`{"error":"already_used","message":"이미 처리된 QR이에요"}`).
- **`type == "stamp"`**: 기존 `POST /stamps`와 동일한 적립 로직(`_earn_stamp`, `app/routers/stamps.py`로 리팩터링해 공유)을 그대로 태운다. 적립이 `400`/`409`(오늘 이미 적립함)로 실패하면 **QR은 소진 처리하지 않고 `WAITING`으로 남겨둔다**(다음에 다시 스캔 가능하도록). 성공하면 QR을 `CONSUMED`로 바꾸고 아래를 반환:
  ```json
  { "kind": "stamp", "store_name": "동네커피 유성점", "amount": null,
    "current": 1, "goal": 5, "reward_reached": false, "reward": null,
    "card_created": true, "reward_coupon": null, "card_reset_to": null,
    "message": "동네커피 유성점 스탬프가 시작됐어요" }
  ```
  `amount`는 스탬프 QR 생성 시 사장님이 선택적으로 넣은 표시용 금액(`POST /admin/qrs/stamp` body의 `amount`, 없으면 `null`)이며 적립 개수 계산에는 쓰이지 않는다.
- **`type == "payment"`**: 즉시 QR을 `CONSUMED`로 바꾸고 아래를 반환. 이후 손님 앱은 이 `store_id`/`amount`로 기존 `GET /checkout/benefits` → `POST /checkout`을 그대로 이어서 호출한다(두 엔드포인트는 변경 없음).
  ```json
  { "kind": "payment", "store_id": 1, "store_name": "동네커피 유성점", "amount": 18000, "checkout_ready": true }
  ```

## `POST /admin/qrs/stamp` (신규, 사장님용)

```json
{ "amount": 4500 }
```
`amount`는 선택(생략 시 `null`) — 화면 표시용일 뿐 적립 로직에 영향 없음. 인증은 기존 `require_owner_id`(`Authorization: Bearer <owner user id>` 또는 `Bearer owner-<id>`) 그대로. 응답은 기존 `POST /admin/qrs/direct`·`/menu`와 같은 `QrCreateResponse` 모양에 `token`/`type` 필드가 추가된 형태:
```json
{ "qrId": 12, "token": "3f9c1e2a7b4d4c1e9f0a2b3c4d5e6f7a", "type": "stamp", "amount": 4500, "qrImage": "/admin/qrs/12/image" }
```

## 레거시 `POST /stamps`는 그대로 유지

프론트/다른 클라이언트가 이미 `customer_token` 방식으로 붙어 있을 수 있어 **삭제하지 않았다.** 내부적으로 `POST /scan`과 같은 적립 로직(`_earn_stamp`)을 공유하도록 리팩터링만 했을 뿐, 요청/응답 계약은 변경 없음. 새 연동은 `POST /scan`을 쓰는 걸 권장.

## 테스트

`app/tests/test_scan.py` 신규 추가 — 스탬프 QR 적립+1회성, 표시용 amount, 결제 QR 스캔 후 `checkout_ready`, 잘못된 토큰(400), 인증 없음(401), 적립 실패 시 QR 재사용 가능 여부까지 커버. 기존 `test_admin.py`/`test_checkout.py`/`test_passes.py`/`test_stamps.py`는 전부 그대로 통과(21개 전체 통과) — 회귀 없음.

> 기존 8-6 `GET /checkout/benefits`, 8-7 `POST /checkout`은 **그대로 유효.** 단 amount의 출처가 "손님 입력"에서 "QR에 실린 값"으로 바뀔 뿐. `POST /scan`이 kind=payment를 반환한 뒤 이 둘을 이어서 호출.