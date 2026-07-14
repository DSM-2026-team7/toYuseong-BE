from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.utils import iso_z

UtcDatetime = Annotated[datetime, PlainSerializer(iso_z, return_type=str)]


# ---------------------------------------------------------------------------
# 1단계: 매장 / 스탬프
# ---------------------------------------------------------------------------


class StampSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current: int
    goal: int


class StoreListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    region: str
    address: Optional[str] = None
    phone_no: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    image_url: Optional[str] = None
    distance_m: Optional[int] = None
    stamp_summary: Optional[StampSummary] = None


class StoreListResponse(BaseModel):
    stores: list[StoreListItem]


class StoreDetailStamp(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    goal: int
    current: int
    reward: str
    condition: str
    stamped_today: bool


class StoreCouponSummary(BaseModel):
    id: int
    type: str
    title: str
    value: int
    valid_until: Optional[UtcDatetime] = None
    claimed_by_me: bool = False


class StoreDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    region: str
    business_hours: str
    address: Optional[str] = None
    phone_no: Optional[str] = None
    image_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    stamp: Optional[StoreDetailStamp] = None
    coupons: list[StoreCouponSummary] = Field(default_factory=list)


class StampRequest(BaseModel):
    store_id: int
    customer_token: str
    amount: Optional[int] = None


class ScanRequest(BaseModel):
    """새 QR 플로우: 가게가 띄운 QR을 손님이 스캔해서 제출할 때 쓰는 요청 바디."""

    qr_token: str


class RewardCoupon(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_coupon_id: int
    title: str
    d_day: int


class StampResponse(BaseModel):
    store_name: str
    current: int
    goal: int
    reward_reached: bool
    reward: Optional[str] = None
    card_created: bool
    reward_coupon: Optional[RewardCoupon] = None
    card_reset_to: Optional[int] = None
    message: str


class ErrorResponse(BaseModel):
    error: str
    message: str


# ---------------------------------------------------------------------------
# 2단계: 쿠폰
# ---------------------------------------------------------------------------


class CouponListItem(BaseModel):
    id: int
    store_name: str
    type: str
    title: str
    value: int
    target: str
    valid_until: Optional[UtcDatetime] = None
    d_day: Optional[int] = None
    time_limit_hours: Optional[int] = None
    store_only: bool
    claimed_by_me: bool
    min_payment: int = 0
    max_discount: Optional[int] = None
    remaining_quantity: Optional[int] = None
    available: bool = True


class CouponListResponse(BaseModel):
    coupons: list[CouponListItem]


class ClaimResponse(BaseModel):
    user_coupon_id: int
    coupon_id: int
    status: str
    claimed_at: UtcDatetime
    message: str


class MyCouponItem(BaseModel):
    user_coupon_id: int
    store_name: str
    type: str
    title: str
    value: int
    status: str
    claimed_at: UtcDatetime
    used_at: Optional[UtcDatetime] = None
    expired_at: Optional[UtcDatetime] = None
    valid_until: Optional[UtcDatetime] = None
    d_day: Optional[int] = None
    min_payment: int = 0
    max_discount: Optional[int] = None


class MyCouponListResponse(BaseModel):
    coupons: list[MyCouponItem]


class CouponDetailStore(BaseModel):
    name: str
    category: str
    region: str
    business_hours: str
    address: Optional[str] = None
    phone_no: Optional[str] = None


class CouponDetailResponse(BaseModel):
    user_coupon_id: int
    store: CouponDetailStore
    type: str
    title: str
    value: int
    target: str
    status: str
    used_at: Optional[UtcDatetime] = None
    expired_at: Optional[UtcDatetime] = None
    valid_until: Optional[UtcDatetime] = None
    d_day: Optional[int] = None
    store_only: bool
    min_payment: int = 0
    max_discount: Optional[int] = None
    usage_note: str


class UseCouponResponse(BaseModel):
    user_coupon_id: int
    status: str
    used_at: UtcDatetime
    message: str


# ---------------------------------------------------------------------------
# 3단계: 결제 혜택 계산 / 결제
# ---------------------------------------------------------------------------


class BenefitItem(BaseModel):
    benefit_id: str
    kind: str
    title: str
    desc: str
    discount: int
    selectable: bool
    reason: Optional[str] = None
    remaining_discount: Optional[int] = None


class CheckoutBenefitsResponse(BaseModel):
    store_name: str
    amount: int
    benefits: list[BenefitItem]


class CheckoutRequest(BaseModel):
    store_id: int
    amount: int
    benefit_id: Optional[str] = "none"
    benefit_ids: list[str] = Field(default_factory=list, max_length=2)
    method: str
    paymentKey: Optional[str] = None
    orderId: Optional[str] = None
    payment_amount: Optional[int] = None
    qr_token: Optional[str] = None


class CheckoutQuoteRequest(BaseModel):
    store_id: int
    amount: int
    benefit_id: Optional[str] = "none"
    benefit_ids: list[str] = Field(default_factory=list, max_length=2)


class CheckoutQuoteResponse(BaseModel):
    store_name: str
    amount: int
    total_discount: int
    final_amount: int
    benefit_ids: list[str]


# ---------------------------------------------------------------------------
# 4단계: 패스
# ---------------------------------------------------------------------------


class PassListItem(BaseModel):
    id: int
    name: str
    scope: str
    period_type: str
    duration_days: int
    price: int
    discount_rate: int
    max_discount_amount: Optional[int] = None
    target_desc: str
    owned: bool


class PassListResponse(BaseModel):
    passes: list[PassListItem]


class PassPriceOption(BaseModel):
    duration_days: int
    price: int


class PassDetailResponse(BaseModel):
    id: int
    name: str
    scope: str
    discount_rate: int
    max_discount_amount: Optional[int] = None
    target_desc: str
    price_options: list[PassPriceOption]
    usage_note: str
    notice: str
    owned: bool


class MyPassItem(BaseModel):
    user_pass_id: int
    name: str
    scope: str
    discount_rate: int
    status: str
    expires_at: UtcDatetime
    d_day: Optional[int] = None
    discount_used: int = 0
    discount_limit: Optional[int] = None
    remaining_discount: Optional[int] = None


class MyPassListResponse(BaseModel):
    passes: list[MyPassItem]


class PassPurchaseRequest(BaseModel):
    duration_days: int
    paymentKey: str
    orderId: str
    amount: int


class PassPurchaseResponse(BaseModel):
    user_pass_id: int
    name: str
    status: str
    expires_at: UtcDatetime
    paid: int
    payment_key: str
    order_id: str
    payment_status: str
    extended: bool = False
    discount_limit: Optional[int] = None
    remaining_discount: Optional[int] = None
    message: str


# ---------------------------------------------------------------------------
# 5단계: 이용내역 / 프로필
# ---------------------------------------------------------------------------


class TransactionItem(BaseModel):
    id: int
    type: str
    store_name: Optional[str] = None
    amount: Optional[int] = None
    memo: Optional[str] = None
    created_at: UtcDatetime


class TransactionsResponse(BaseModel):
    transactions: list[TransactionItem]
    next_cursor: Optional[str] = None


class MeResponse(BaseModel):
    id: int
    nickname: str
    region: str
    role: str
    unread_notifications: int
    email: Optional[str] = None
    profile_image_url: Optional[str] = None
    roles: list[str] = Field(default_factory=list)
    onboarding_completed: bool = True
    location_permission: str = "unknown"
    store_verification: Literal["none", "pending", "approved"] = "none"


class MyStampItem(BaseModel):
    stamp_card_id: int
    store_id: int
    store_name: str
    current: int
    goal: int
    reward: str
    updated_at: UtcDatetime
    expires_at: Optional[UtcDatetime] = None
    d_day: Optional[int] = None


class MyStampListResponse(BaseModel):
    stamps: list[MyStampItem]


# ---------------------------------------------------------------------------
# 알림 (명세 API.md에는 없는 목업 부가 기능 — 알림 아이콘/뱃지 데모용)
# ---------------------------------------------------------------------------


class NotificationItem(BaseModel):
    id: int
    title: str
    body: str
    read: bool
    created_at: UtcDatetime


class NotificationsResponse(BaseModel):
    notifications: list[NotificationItem]


# ---------------------------------------------------------------------------
# 데모 로그인 (역할 선택) — 비밀번호 없이 사용자/사장님 계정을 골라 로그인한다.
# ---------------------------------------------------------------------------


class AuthAccountItem(BaseModel):
    role: Literal["customer", "owner"]
    user_id: int
    nickname: str
    store_id: Optional[int] = None
    store_name: Optional[str] = None


class AuthAccountsResponse(BaseModel):
    accounts: list[AuthAccountItem]


class AuthLoginRequest(BaseModel):
    role: Literal["customer", "owner"]
    user_id: int


class AuthLoginResponse(BaseModel):
    role: Literal["customer", "owner"]
    user_id: int
    nickname: str
    region: Optional[str] = None
    store_id: Optional[int] = None
    store_name: Optional[str] = None
    token: Optional[str] = None


class GoogleLoginRequest(BaseModel):
    credential: str


class GoogleLoginResponse(BaseModel):
    user_id: int
    token: str
    role: str
    roles: list[str]
    is_new: bool
    requires_role_selection: bool
    nickname: str
    email: Optional[str] = None
    profile_image_url: Optional[str] = None
    store_verification: Literal["none", "pending", "approved"] = "none"


class RoleSelectRequest(BaseModel):
    role: Literal["customer", "owner"]
    region: Optional[str] = None


class RoleSwitchResponse(BaseModel):
    role: Literal["customer", "owner"]
    roles: list[str]
    store_verification_required: bool
    store_verification: Literal["none", "pending", "approved"] = "none"


class UserPreferencesRequest(BaseModel):
    location_permission: Optional[Literal["granted", "denied", "unknown"]] = None
    region: Optional[str] = None


class LogoutResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# 장소 검색 API (네이버 지역 검색)
# ---------------------------------------------------------------------------


class PlaceSearchItem(BaseModel):
    name: str
    category: Optional[str] = None
    address: Optional[str] = None
    road_address: Optional[str] = None
    phone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str = "naver"


class PlaceSearchResponse(BaseModel):
    places: list[PlaceSearchItem]

# ---------------------------------------------------------------------------
# 관리자 API
# ---------------------------------------------------------------------------


class AdminRegisterRequest(BaseModel):
    name: str
    register_num: str
    category: Literal["cafe", "rest", "beauty", "etc"] = "etc"
    address: str
    region: Optional[str] = None
    business_hours: Optional[str] = None
    phone_no: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AdminStoreResponse(BaseModel):
    id: int
    name: str
    category: str
    region: str
    business_hours: Optional[str] = None
    phone_no: Optional[str] = None
    register_num: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    verification_status: str = "approved"


class AdminStoreUpdateRequest(BaseModel):
    name: Optional[str] = None
    register_num: Optional[str] = None
    category: Optional[Literal["cafe", "rest", "beauty", "etc"]] = None
    address: Optional[str] = None
    region: Optional[str] = None
    business_hours: Optional[str] = None
    phone_no: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class StoreVerificationResponse(BaseModel):
    status: Literal["none", "pending", "approved"]
    application_id: Optional[int] = None
    store_id: Optional[int] = None
    reject_reason: Optional[str] = None
    message: str


class OwnerDashboardResponse(BaseModel):
    store_id: int
    store_name: str
    settlement_expected: int
    settlement_status: Literal["pending", "completed"] = "pending"
    settled_amount: int = 0
    coupon_issued: int
    coupon_used: int
    coupon_remaining: Optional[int] = None
    has_unlimited_coupon: bool
    active_coupon_count: int
    stopped_coupon_count: int
    stamp_configured: bool


class AdminCouponPercentRequest(BaseModel):
    type: Literal["percent"]
    coupon_name: Optional[str] = None
    sale_percent: float
    sale_max: Optional[int] = None
    min_buy_price: int = 0
    coupon_num: Optional[int] = Field(default=None, ge=1)
    is_coupon_infinity: bool = False
    is_apply_all: bool = False
    expiry_date: Optional[datetime] = None
    valid_days: Optional[int] = Field(default=None, gt=0)


class AdminCouponStampRequest(BaseModel):
    type: Literal["stamp"]
    stamp_max_require: int
    reward_content: str
    is_visit_stamp: bool = False
    expiry_date: Optional[datetime] = None


class AdminCouponFixedRequest(BaseModel):
    type: Literal["fixed"]
    coupon_name: Optional[str] = None
    sale_price: int
    min_buy_price: int = 0
    expiry_date: Optional[datetime] = None
    valid_days: Optional[int] = Field(default=None, gt=0)
    coupon_num: Optional[int] = Field(default=None, ge=1)
    is_coupon_infinity: bool = False


AdminCouponRequest = Annotated[
    Union[AdminCouponPercentRequest, AdminCouponStampRequest, AdminCouponFixedRequest],
    Field(discriminator="type"),
]


class MenuRequest(BaseModel):
    name: str
    price: int


class MenuUpdateRequest(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = None


class MenuResponse(BaseModel):
    menuId: int
    name: str
    price: int


class MenuQrRequest(BaseModel):
    menuIds: list[int]
    qr_type: Literal["payment", "stamp"] = "payment"


class DirectQrRequest(BaseModel):
    amount: int


class StampQrRequest(BaseModel):
    amount: Optional[int] = None
    menuIds: list[int] = Field(default_factory=list)


class QrCreateResponse(BaseModel):
    qrId: int
    token: str
    type: str
    amount: Optional[int] = None
    qrImage: str
    expiresAt: Optional[UtcDatetime] = None


class QrResponse(QrCreateResponse):
    status: str


class PaymentResponse(BaseModel):
    paymentId: int
    amount: int
    status: str
    originalAmount: Optional[int] = None
    discountAmount: int = 0
    benefitSummary: Optional[str] = None
    completedAt: Optional[UtcDatetime] = None


class PaymentQrResultResponse(BaseModel):
    qrId: int
    status: str
    amount: Optional[int] = None
    paymentId: Optional[int] = None
    paidAmount: Optional[int] = None
    discountAmount: Optional[int] = None
    benefitSummary: Optional[str] = None
    completedAt: Optional[UtcDatetime] = None


class StampPolicyRequest(BaseModel):
    goal: int = Field(ge=1)
    min_amount: int = Field(ge=0)
    completion_limit: Optional[int] = Field(default=None, ge=1)
    reward_name: str
    reward_type: Literal["discount_rate", "discount_amount"]
    reward_value: int = Field(ge=0)
    reward_min_payment: int = Field(default=0, ge=0)
    reward_max_discount: Optional[int] = Field(default=None, ge=0)
    reward_valid_days: Optional[int] = Field(default=30, ge=1)
    active: bool = True


class StampPolicyResponse(BaseModel):
    configured: bool
    id: Optional[int] = None
    goal: Optional[int] = None
    min_amount: Optional[int] = None
    completion_limit: Optional[int] = None
    reward_name: Optional[str] = None
    reward_type: Optional[str] = None
    reward_value: Optional[int] = None
    reward_min_payment: Optional[int] = None
    reward_max_discount: Optional[int] = None
    reward_valid_days: Optional[int] = None
    active: bool = False


class AdminStampResponse(BaseModel):
    shopName: str
    currentStamp: int
    maxStamp: int
