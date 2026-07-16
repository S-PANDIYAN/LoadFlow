"""Pydantic v2 request/response schemas."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.enums import AccountType, LoadState, AuthorityStatus


# ---- Auth ----

class OrgRegister(BaseModel):
    organization_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6)


class ShipperRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    account_type: AccountType
    is_org_admin: bool


class UserOut(BaseModel):
    id: int
    full_name: str
    email: str
    account_type: AccountType
    organization_id: int | None
    organization_name: str | None = None
    is_org_admin: bool
    is_active: bool
    permissions: list[str] = []
    roles: list[str] = []

    model_config = {"from_attributes": True}


# ---- RBAC ----

class PermissionOut(BaseModel):
    id: int
    code: str
    description: str
    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    permission_codes: list[str] = []


class RoleUpdatePermissions(BaseModel):
    permission_codes: list[str]


class RoleOut(BaseModel):
    id: int
    name: str
    organization_id: int
    permission_codes: list[str] = []
    model_config = {"from_attributes": True}


class StaffCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6)
    role_ids: list[int] = []


class AssignRole(BaseModel):
    user_id: int
    role_id: int


# ---- Compliance ----

class ComplianceUpsert(BaseModel):
    insurance_expiry: datetime | None = None
    mc_number: str | None = None
    dot_number: str | None = None
    authority_status: AuthorityStatus = AuthorityStatus.ACTIVE
    approved_equipment: str = ""    # comma-separated
    approved_commodities: str = ""  # comma-separated


class ComplianceOut(BaseModel):
    id: int
    carrier_org_id: int
    carrier_org_name: str | None = None
    insurance_expiry: datetime | None
    mc_number: str | None
    dot_number: str | None
    authority_status: AuthorityStatus
    approved_equipment: str
    approved_commodities: str
    updated_at: datetime
    model_config = {"from_attributes": True}


# ---- Loads ----

class LoadCreate(BaseModel):
    origin: str = Field(min_length=2, max_length=120)
    destination: str = Field(min_length=2, max_length=120)
    equipment_type: str = Field(min_length=2, max_length=60)
    commodity: str = Field(min_length=2, max_length=60)
    weight_lbs: int | None = None
    pickup_date: datetime | None = None
    shipper_email: EmailStr  # broker links load to a shipper account


class AssignCarrier(BaseModel):
    carrier_org_id: int


class TransitionRequest(BaseModel):
    to_state: LoadState
    note: str | None = None


class OverrideRequest(BaseModel):
    note: str = Field(min_length=3, max_length=500)  # override must be justified


class RateConfCreate(BaseModel):
    base_rate: float = Field(gt=0)
    accessorials: list[dict] = []  # [{"name": "detention", "amount": 150.0}]


class RateConfOut(BaseModel):
    id: int
    load_id: int
    version: int
    base_rate: float
    accessorials: str
    confirmed: bool
    confirmed_by: int | None
    confirmed_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}


class PodRequest(BaseModel):
    note: str | None = None


class LoadEventOut(BaseModel):
    id: int
    event_type: str
    from_state: str | None
    to_state: str | None
    note: str | None
    actor_name: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class LoadOut(BaseModel):
    id: int
    reference: str
    origin: str
    destination: str
    equipment_type: str
    commodity: str
    weight_lbs: int | None
    pickup_date: datetime | None
    state: LoadState
    shipper_id: int
    shipper_name: str | None = None
    broker_org_id: int
    carrier_org_id: int | None
    carrier_org_name: str | None = None
    compliance_flagged: bool
    compliance_reason: str | None
    compliance_overridden: bool
    rate_confirmation_id: int | None
    pod_uploaded: bool
    created_at: datetime
    model_config = {"from_attributes": True}
