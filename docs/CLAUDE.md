# 유성으로 (ToYuseong) — 백엔드

유성구 로컬 상권 스탬프/쿠폰/패스 앱의 백엔드. 교내 해커톤 프로젝트.
API 규격은 docs폴더의 **`API.md`** 를 단일 진실 소스(source of truth)로 삼는다. 구현 전 항상 이 문서를 먼저 확인할 것.

## 기술 스택 (고정 — 임의로 바꾸지 말 것)

- Python 3.11+, **FastAPI**
- **SQLAlchemy 2.0 (동기 방식)** + **SQLite**. async/AsyncSession 쓰지 말 것 — 해커톤이라 단순함이 우선.
- **Pydantic v2** (`ConfigDict(from_attributes=True)` 사용)
- 서버 실행: `fastapi dev app/main.py`
- 패키지 설치: `pip install "fastapi[standard]" sqlalchemy`

> Postgres, Alembic, Docker, async, 별도 인증 서버 등 **명세에 없는 인프라를 임의로 추가하지 말 것.** 필요하다고 판단되면 먼저 물어볼 것.

## 프로젝트 구조

```
app/
  main.py          # FastAPI 앱 + 라우터 등록 + CORS
  database.py      # engine, SessionLocal, Base, get_db 의존성
  models.py        # SQLAlchemy ORM 모델 (명세 2·7절)
  schemas.py       # Pydantic 요청/응답 스키마 (명세의 JSON 예시 기준)
  seed.py          # 궁동 상권 더미 데이터 삽입
  routers/
    stores.py
    coupons.py
    stamps.py
    passes.py
    checkout.py
    me.py
    auth.py
  tests/
    test_stamps.py # 최소한 스탬프 루프 E2E 테스트
```

## 핵심 규칙 / 도메인 로직

이 앱만의 규칙이라 놓치기 쉬움. 반드시 지킬 것:

1. **인증은 데모용으로 간소화.** Google OAuth를 실제 구현하지 말 것. 모든 인증은 요청 헤더 `X-User-Id: <int>` 로 현재 사용자를 식별한다. `POST /auth/google`는 목업으로 두거나 후순위.
2. **스탬프는 방문/결제당 1개**, 하루 최대 1개(`condition: "1일 1회·결제 시"`). 같은 날 재적립 요청은 `409 already_stamped_today`.
3. **첫 적립 시 StampCard 자동 생성** (`card_created: true`).
4. **5/5 도달 시**: ①리워드 쿠폰을 UserCoupon으로 자동 발급 → ②해당 StampCard.current를 0으로 리셋 (`card_reset_to: 0`). 이 두 동작은 한 트랜잭션에서.
5. **쿠폰/패스 상태는 조건부 필드가 핵심** (명세 4절 표). 예: `user_coupon.status == used` 이면 `used_at`만 값, `expired_at`은 null. 반드시 이 규칙대로 응답.
6. **결제 혜택 계산** (`GET /checkout/benefits`, 명세 8-6): 정률 쿠폰은 `max_discount` 상한 적용, `min_payment` 미달이면 `selectable: false` + `reason`. 쿠폰과 패스를 하나의 `benefits[]` 목록으로 합쳐 응답.
7. **모든 결제/적립/발급 액션은 Transaction 한 줄을 남긴다** (이용내역 `GET /me/transactions` 가 이걸 읽음).
8. **에러 응답 형식 통일**: `{ "error": "snake_case_code", "message": "사용자용 한글 안내" }` + 적절한 HTTP 상태. message는 화면 토스트에 그대로 쓰이므로 명세의 문구를 따를 것.
9. **QR 방식은 아직 미확정.** 백엔드는 `POST /stamps`가 `store_id` + `customer_token`(손님 식별값)을 받는 것으로 구현하면 방향과 무관하게 동작함. 임의로 회전 QR 검증 로직 등을 넣지 말 것.

## 응답/스키마 원칙

- 응답 JSON은 **명세서의 예시와 필드명·타입이 정확히 일치**해야 한다. 임의로 필드명을 바꾸거나 추가하지 말 것.
- 날짜는 ISO8601 UTC 문자열. `d_day`는 서버가 계산해서 int로 내려줌.
- 목록이 비면 빈 배열 `[]` 반환 (null 아님).

## 개발 순서 (명세 5·9절 우선순위)

지시 없이 전부 만들지 말 것. 한 번에 한 단계씩, 각 단계 후 동작 확인.
1. DB/모델/시드 + 스탬프 루프: `GET /stores`, `GET /stores/{id}`, `POST /stamps` (첫적립·5/5리셋·409·400 포함)
2. 쿠폰: `GET /coupons`, `POST /coupons/{id}/claim`, `GET /me/coupons`
3. 결제: `GET /checkout/benefits`, `POST /checkout`
4. 패스: `GET /passes`, `POST /passes/{id}/purchase`, `GET /me/passes`
5. 이용내역/프로필: `GET /me/transactions`, `GET /me`

## 검증

- 각 단계 후 `fastapi dev`로 서버가 뜨는지, `/docs` (Swagger)에서 해당 엔드포인트가 실제로 도는지 확인.
- 스탬프 루프는 `tests/test_stamps.py`로 E2E 테스트 (인메모리 SQLite, TestClient). 최소: 적립→409중복→5/5도달시 리워드발급+리셋.

## 프론트 연동

- CORS 허용 (개발 중엔 `allow_origins=["*"]`).
- 프론트 팀은 `/docs`를 보고 붙임. 응답 스키마가 명세와 어긋나면 프론트가 깨지므로 명세 준수가 최우선.