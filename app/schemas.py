from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, PlainSerializer

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


class StoreDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    region: str
    business_hours: str
    stamp: StoreDetailStamp


class StampRequest(BaseModel):
    store_id: int
    customer_token: str
    amount: Optional[int] = None


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


class MyCouponListResponse(BaseModel):
    coupons: list[MyCouponItem]


class CouponDetailStore(BaseModel):
    name: str
    category: str
    region: str
    business_hours: str


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


class CheckoutBenefitsResponse(BaseModel):
    store_name: str
    amount: int
    benefits: list[BenefitItem]


class CheckoutRequest(BaseModel):
    store_id: int
    amount: int
    benefit_id: str
    method: str


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
    d_day: int


class MyPassListResponse(BaseModel):
    passes: list[MyPassItem]


class PassPurchaseRequest(BaseModel):
    duration_days: int


class PassPurchaseResponse(BaseModel):
    user_pass_id: int
    name: str
    status: str
    expires_at: UtcDatetime
    paid: int
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
