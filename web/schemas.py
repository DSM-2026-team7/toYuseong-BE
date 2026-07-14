from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.utils import iso_z

UtcDatetime = Annotated[datetime, PlainSerializer(iso_z, return_type=str)]


# ---------------------------------------------------------------------------
# 대시보드
# ---------------------------------------------------------------------------


class DashboardStats(BaseModel):
    total_coupons_issued: int
    total_coupons_used: int
    registered_stores: int
    estimated_subsidy: int


class RecentActivityItem(BaseModel):
    timestamp: UtcDatetime
    type: str
    type_label: str
    store_name: Optional[str] = None
    content: str
    status: str
    note: Optional[str] = None


class DashboardResponse(BaseModel):
    stats: DashboardStats
    recent_activities: list[RecentActivityItem]
    pending_applications: int
    total_applications_reviewed: int


# ---------------------------------------------------------------------------
# 가맹점 심사
# ---------------------------------------------------------------------------


class ApplicationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    region: str
    applicant_name: str
    applied_at: UtcDatetime
    status: str
    application_type: str = "initial"


class ApplicationCounts(BaseModel):
    pending: int
    approved: int
    rejected: int


class ApplicationListResponse(BaseModel):
    applications: list[ApplicationListItem]
    counts: ApplicationCounts


class ApplicationDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    business_number: str
    category: str
    region: str
    business_hours: str
    phone: str
    address: Optional[str] = None
    applicant_name: str
    status: str
    reject_reason: Optional[str] = None
    applied_at: UtcDatetime
    reviewed_at: Optional[UtcDatetime] = None
    application_type: str = "initial"
    store_id: Optional[int] = None


class ApplicationCreateRequest(BaseModel):
    name: str
    category: str
    region: str
    business_number: str
    business_hours: str
    phone: str
    applicant_name: str
    address: Optional[str] = None


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("반려 사유를 입력해 주세요")
        return value


class ApplicationActionResponse(BaseModel):
    id: int
    status: str
    message: str


# ---------------------------------------------------------------------------
# 정산 관리
# ---------------------------------------------------------------------------


class SettlementStats(BaseModel):
    total_subsidy: int
    pending_amount: int
    completed_amount: int


class SettlementStoreItem(BaseModel):
    store_id: int
    store_name: str
    transaction_count: int
    subsidy_amount: int
    status: str  # pending | completed


class SettlementListResponse(BaseModel):
    stats: SettlementStats
    stores: list[SettlementStoreItem]
    year: int
    month: int


class SettlementTransactionItem(BaseModel):
    timestamp: UtcDatetime
    user_name: str
    payment_amount: int
    discount_rate: int
    discount_amount: int
    note: Optional[str] = None


class SettlementDetailResponse(BaseModel):
    store_id: int
    store_name: str
    year: int
    month: int
    transaction_count: int
    total_subsidy: int
    transactions: list[SettlementTransactionItem]
    status: str = "pending"
    processed_at: Optional[UtcDatetime] = None


class SettlementProcessResponse(BaseModel):
    store_id: int
    store_name: str
    amount: int
    status: str
    message: str
    transaction_count: int = 0
    processed_at: Optional[UtcDatetime] = None


class SettlementBatchProcessResponse(BaseModel):
    year: int
    month: int
    processed_store_count: int
    total_amount: int
    stores: list[SettlementProcessResponse]
    message: str


# ---------------------------------------------------------------------------
# 패스 관리
# ---------------------------------------------------------------------------


class PassPriceTierItem(BaseModel):
    duration_days: int
    price: int

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("가격은 0보다 커야 해요")
        return v

    @field_validator("duration_days")
    @classmethod
    def duration_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("기간은 0일보다 길어야 해요")
        return v


class AdminPassListItem(BaseModel):
    id: int
    name: str
    scope: str
    scope_category: Optional[str] = None
    discount_rate: int
    duration_days: int
    price: int
    max_discount_amount: Optional[int] = Field(default=None, gt=0)
    price_tiers: list[PassPriceTierItem]
    sale_status: str


class AdminPassListResponse(BaseModel):
    passes: list[AdminPassListItem]


class AdminPassDetailResponse(BaseModel):
    id: int
    name: str
    scope: str
    scope_category: Optional[str] = None
    scope_store_id: Optional[int] = None
    discount_rate: int
    target_desc: str
    max_discount_amount: Optional[int] = Field(default=None, gt=0)
    price_tiers: list[PassPriceTierItem]
    sale_status: str


class AdminPassCreateRequest(BaseModel):
    name: str
    scope: str = "all"
    scope_category: Optional[str] = None
    scope_store_id: Optional[int] = None
    discount_rate: int = 10
    target_desc: str = "패스 할인"
    price_tiers: list[PassPriceTierItem] = Field(default_factory=list)
    duration_days: Optional[int] = Field(default=None, gt=0)
    price: Optional[int] = Field(default=None, gt=0)
    sale_status: Literal["on_sale", "stopped"] = "on_sale"
    max_discount_amount: Optional[int] = Field(default=None, gt=0)

    @field_validator("discount_rate")
    @classmethod
    def discount_rate_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("할인율은 0보다 커야 해요")
        return v


class AdminPassUpdateRequest(BaseModel):
    name: Optional[str] = None
    scope: Optional[str] = None
    scope_category: Optional[str] = None
    scope_store_id: Optional[int] = None
    discount_rate: Optional[int] = None
    target_desc: Optional[str] = None
    price_tiers: list[PassPriceTierItem] = Field(default_factory=list)
    duration_days: Optional[int] = Field(default=None, gt=0)
    price: Optional[int] = Field(default=None, gt=0)
    sale_status: Optional[Literal["on_sale", "stopped"]] = None
    max_discount_amount: Optional[int] = Field(default=None, gt=0)

    @field_validator("discount_rate")
    @classmethod
    def discount_rate_must_be_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("할인율은 0보다 커야 해요")
        return v


class AdminPassResponse(BaseModel):
    id: int
    message: str


class PassStatusRequest(BaseModel):
    sale_status: Literal["on_sale", "stopped"]
