import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils import utc_now as utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nickname: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="customer")
    google_sub: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    owner_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    location_permission: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    business_hours: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    register_num: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    phone_no: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_status: Mapped[str] = mapped_column(String, nullable=False, default="approved")


class StampPolicy(Base):
    __tablename__ = "stamp_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, unique=True)
    goal: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    reward: Mapped[str] = mapped_column(String, nullable=False)
    condition: Mapped[str] = mapped_column(String, nullable=False, default="1일 1회·결제 시")
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reward_type: Mapped[str] = mapped_column(String, nullable=False, default="discount_amount")
    reward_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reward_min_payment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reward_max_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reward_valid_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=30)


class StampCard(Base):
    __tablename__ = "stamp_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Coupon(Base):
    """매장이 발급 중인 쿠폰 원본. 스탬프 5/5 리워드 쿠폰도 이 테이블에 개별 발급된다."""

    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    time_limit_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    store_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_payment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_discount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coupon_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_coupon_infinity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_apply_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="owner")


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)


class PaymentQr(Base):
    """가게가 만들어 화면에 띄우는 1회용 QR. type으로 스탬프용/결제용을 구분한다.

    token은 QR에 실제로 인코딩되는 추측 불가 문자열(uuid4 hex)이고, id는 내부 PK다.
    손님 스캔(POST /scan)은 이 token으로 조회한다. 스탬프 QR은 적립 성공 시,
    결제 QR은 POST /checkout의 결제 완료 시 status를 CONSUMED로 바꾼다.
    """

    __tablename__ = "payment_qrs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, default=lambda: uuid.uuid4().hex)
    type: Mapped[str] = mapped_column(String, nullable=False, default="payment")
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="WAITING")
    qr_image: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    qr_id: Mapped[int | None] = mapped_column(ForeignKey("payment_qrs.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="WAITING")
    original_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    benefit_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TossPayment(Base):
    """토스 승인 결과와 로컬 지급 결과를 연결하는 결제 원장.

    기존 SQLite 파일에도 ``create_all``만으로 추가될 수 있도록 기존 payments
    테이블을 변경하지 않고 별도 테이블로 둔다.
    """

    __tablename__ = "toss_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str | None] = mapped_column(String, nullable=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    pass_id: Mapped[int | None] = mapped_column(ForeignKey("passes.id"), nullable=True)
    checkout_payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    user_pass_id: Mapped[int | None] = mapped_column(ForeignKey("user_passes.id"), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class UserCoupon(Base):
    __tablename__ = "user_coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    claimed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Pass(Base):
    """패스 마켓에 진열되는 상품 원본.

    scope_category / scope_store_id는 명세 7절 모델에는 없지만, scope가
    "category"/"store"일 때 실제로 어느 업종·매장에 적용되는지 서버 내부적으로
    알아야 결제 혜택 계산(8-6)이 가능해서 추가한 내부용 필드다. API 응답에는 노출하지 않는다.
    """

    __tablename__ = "passes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    period_type: Mapped[str] = mapped_column(String, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    max_discount_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_desc: Mapped[str] = mapped_column(String, nullable=False)
    usage_note: Mapped[str] = mapped_column(
        String, nullable=False, default="결제 시 사장님의 결제 QR을 스캔하고 이 패스를 선택하면 할인이 적용돼요."
    )
    scope_category: Mapped[str | None] = mapped_column(String, nullable=True)
    scope_store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    sale_status: Mapped[str] = mapped_column(String, nullable=False, default="on_sale")


class UserPass(Base):
    __tablename__ = "user_passes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    pass_id: Mapped[int] = mapped_column(ForeignKey("passes.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    purchased_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    discount_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    scope_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    scope_category_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    scope_store_id_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_rate_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_discount_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    store_name: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memo: Mapped[str | None] = mapped_column(String, nullable=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    discount_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Notification(Base):
    """알림 아이콘/뱃지 데모용 목업 테이블. 명세(API.md)에는 없는 부가 기능이다."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


# ---------------------------------------------------------------------------
# 구청 관리자용 모델 (web/)
# ---------------------------------------------------------------------------


class StoreApplication(Base):
    """가맹점 신청·심사 테이블."""

    __tablename__ = "store_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    business_number: Mapped[str] = mapped_column(String, nullable=False)
    business_hours: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    applicant_name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    application_type: Mapped[str] = mapped_column(String, nullable=False, default="initial")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Settlement(Base):
    """패스 사용 보전금 정산 기록."""

    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint("store_id", "year", "month", name="uq_settlement_store_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PassPriceTier(Base):
    """패스 기간별 가격 옵션."""

    __tablename__ = "pass_price_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pass_id: Mapped[int] = mapped_column(ForeignKey("passes.id"), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)


class AdminUser(Base):
    """구청 관리자 계정."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

