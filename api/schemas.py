"""Pydantic request/response models for the CapEigen API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "capeigen-api"
    data_backend: str = "supabase"


class MeResponse(BaseModel):
    id: str
    email: str | None = None
    username: str | None = None
    is_admin: bool = False
    is_preview: bool = False


class PreviewEventCreateRequest(BaseModel):
    event_type: str = Field(min_length=2, max_length=40)
    path: str | None = Field(default=None, max_length=300)
    label: str | None = Field(default=None, max_length=400)
    payload: dict[str, Any] = Field(default_factory=dict)


class PreviewEventListResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int


class UsageSummaryResponse(BaseModel):
    days: int
    audience: str
    totals: dict[str, int]
    actions: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    users: list[dict[str, Any]]


class LegalDocumentResponse(BaseModel):
    slug: str
    title: str
    body: str
    effective_date: str
    updated_at: str | None = None
    updated_by: str | None = None
    is_default: bool = False


class LegalDocumentUpdateRequest(BaseModel):
    body: str = Field(min_length=40)
    title: str | None = Field(default=None, max_length=120)
    effective_date: str | None = Field(default=None, max_length=10)


class PreviewAccountCreateRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)


class PreviewAccount(BaseModel):
    username: str
    active: bool
    source: str
    created_at: str | None = None
    created_by: str | None = None
    last_seen: str | None = None
    event_count: int = 0
    login_count: int = 0
    analyze_count: int = 0
    compare_count: int = 0
    pdf_count: int = 0


class PreviewAccountListResponse(BaseModel):
    accounts: list[PreviewAccount]
    count: int


class PreviewLoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)


class PreviewLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    username: str


class AddressSearchResponse(BaseModel):
    addresses: list[str]


class AnalysisStartRequest(BaseModel):
    address: str = Field(min_length=3)
    guest_mode: bool = False


class AnalysisStartResponse(BaseModel):
    job_id: str
    status: str
    property_data: dict[str, Any] | None = None
    deferred_tasks: list[str] = Field(default_factory=list)
    deferred_tasks_total: int = 0
    from_kb: bool = False
    error: str | None = None


class AnalysisJobResponse(BaseModel):
    job_id: str
    status: str
    property_data: dict[str, Any] | None = None
    deferred_tasks: list[str] = Field(default_factory=list)
    deferred_tasks_total: int = 0
    completed_tasks: list[str] = Field(default_factory=list)
    error: str | None = None
    address: str | None = None
    from_kb: bool = False


class FinanceRecalcRequest(BaseModel):
    price: float
    down_payment_pct: float = 25.0
    interest_rate: float = 6.0
    loan_term: int = 30
    closing_costs_pct: float = 3.0
    tax_rate: float = 1.2
    monthly_insurance: float = 150.0
    monthly_hoa: float = 0.0
    maint_percent: float = 1.0
    monthly_rent: float
    vacancy_reserve_pct: float = 5.0
    management_fee_pct: float = 8.0
    job_id: str | None = None
    location_score: float | None = None
    forecast_rate: float | None = None


class FinanceRecalcResponse(BaseModel):
    finance: dict[str, Any]
    quantum_requeued: bool = False


class SaveOverrideRequest(BaseModel):
    property_id: str
    address: str | None = None
    rent: float | None = None
    maint_percent: float | None = None
    vacancy_rate: float | None = None
    management_fee: float | None = None
    is_outlier: bool = False
    override_notes: str = ""
    property_data: dict[str, Any] | None = None
    save_canonical: bool = False


class BookmarkRequest(BaseModel):
    property_id: str | None = None
    address: str | None = None
    property_data: dict[str, Any] | None = None


class PropertyViewRequest(BaseModel):
    property_id: str = Field(min_length=1, max_length=80)


class PropertyViewResponse(BaseModel):
    property_id: str
    app_view_count: int


class PropertyOfDayResponse(BaseModel):
    show: bool
    feature_date: str
    viewer_date: str
    property: dict[str, Any] | None = None
    reasons: list[str] = Field(default_factory=list)


class ShareCreateRequest(BaseModel):
    property_id: str
    include_assumptions: bool = True
    expires_days: int = 30
    property_data: dict[str, Any] | None = None
    base_url: str | None = None


class ShareCreateResponse(BaseModel):
    share_token: str
    share_url: str


class CompareRequest(BaseModel):
    addresses: list[str] = Field(min_length=1, max_length=4)
    down_payment_pct: float = 25.0
    interest_rate: float = 6.0
    loan_term: int = 30
    closing_costs_pct: float = 3.0


class CompareResponse(BaseModel):
    properties: list[dict[str, Any]]
    metrics: list[dict[str, Any]]


class PdfRequest(BaseModel):
    address: str
    property_info: dict[str, Any]
    metrics: dict[str, Any]
    # pdf_generator expects {Description: [...], Amount: [...]}; lists of [label, amount] also accepted.
    table_data: dict[str, Any] | list[Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    location_score: float = 5.0
    quantum_risk: dict[str, Any] | None = None
    forecast_display: dict[str, Any] | None = None


class ValidationMetricsResponse(BaseModel):
    row_count: int
    price_label: str
    price_n: int
    price_mape_pct: float | None
    price_rmse: float | None
    rent_label: str
    rent_n: int
    rent_mape_pct: float | None
    rent_rmse: float | None
    report_text: str
    calibration_png_base64: str | None = None
