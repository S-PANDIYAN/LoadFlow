"""All SQLAlchemy models: RBAC foundation + freight domain.

RBAC design: Permission (global catalog) <- RolePermission -> Role (org-scoped,
admin-created) <- UserRole -> User. Authorization code checks permission CODES,
never role names.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import OrgType, AccountType, LoadState, AuthorityStatus


def utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# RBAC / Identity
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    organization_type: Mapped[OrgType] = mapped_column(Enum(OrgType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    roles: Mapped[list["Role"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True  # NULL for shippers
    )
    is_org_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    organization: Mapped["Organization | None"] = relationship(back_populates="users")
    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="user")


class Permission(Base):
    """Global, immutable permission catalog — seeded at startup."""
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)


class Role(Base):
    """Org-scoped role created dynamically by org admins. Never hardcoded."""
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_role_org_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="roles")
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"), primary_key=True)

    role: Mapped["Role"] = relationship(back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship()


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)

    user: Mapped["User"] = relationship(back_populates="user_roles")
    role: Mapped["Role"] = relationship()


# ---------------------------------------------------------------------------
# Freight domain
# ---------------------------------------------------------------------------

class CarrierCompliance(Base):
    """One compliance record per carrier org: insurance, authority, equipment."""
    __tablename__ = "carrier_compliance"

    id: Mapped[int] = mapped_column(primary_key=True)
    carrier_org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), unique=True, nullable=False
    )
    insurance_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mc_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dot_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    authority_status: Mapped[AuthorityStatus] = mapped_column(
        Enum(AuthorityStatus), default=AuthorityStatus.ACTIVE
    )
    # comma-separated lists — simple + queryable enough for hackathon scope
    approved_equipment: Mapped[str] = mapped_column(String(255), default="")
    approved_commodities: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    carrier_org: Mapped["Organization"] = relationship()


class Load(Base):
    __tablename__ = "loads"
    __table_args__ = (
        Index("ix_loads_broker_org", "broker_org_id"),
        Index("ix_loads_carrier_org", "carrier_org_id"),
        Index("ix_loads_shipper", "shipper_id"),
        Index("ix_loads_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    origin: Mapped[str] = mapped_column(String(120), nullable=False)
    destination: Mapped[str] = mapped_column(String(120), nullable=False)
    equipment_type: Mapped[str] = mapped_column(String(60), nullable=False)
    commodity: Mapped[str] = mapped_column(String(60), nullable=False)
    weight_lbs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pickup_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    state: Mapped[LoadState] = mapped_column(Enum(LoadState), default=LoadState.POSTED)

    # Three-way linkage: shipper + broker org + assigned carrier org
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    broker_org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    carrier_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)

    # Compliance flag: blocks progression past CARRIER_ASSIGNED until resolved/overridden
    compliance_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    compliance_overridden: Mapped[bool] = mapped_column(Boolean, default=False)

    # The rate confirmation version actually confirmed for this load (immutable link)
    rate_confirmation_id: Mapped[int | None] = mapped_column(
        ForeignKey("rate_confirmations.id"), nullable=True
    )

    pod_uploaded: Mapped[bool] = mapped_column(Boolean, default=False)
    pod_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    shipper: Mapped["User"] = relationship(foreign_keys=[shipper_id])
    broker_org: Mapped["Organization"] = relationship(foreign_keys=[broker_org_id])
    carrier_org: Mapped["Organization | None"] = relationship(foreign_keys=[carrier_org_id])
    rate_confirmation: Mapped["RateConfirmation | None"] = relationship(
        foreign_keys=[rate_confirmation_id]
    )
    events: Mapped[list["LoadEvent"]] = relationship(
        back_populates="load", order_by="LoadEvent.created_at",
        foreign_keys="LoadEvent.load_id",
    )


class RateConfirmation(Base):
    """Versioned broker-carrier rate agreement. Rows are IMMUTABLE —
    a re-negotiation creates a new version; old loads keep the version
    they actually confirmed."""
    __tablename__ = "rate_confirmations"
    __table_args__ = (
        UniqueConstraint("load_id", "version", name="uq_rateconf_load_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("loads.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_rate: Mapped[float] = mapped_column(Float, nullable=False)
    accessorials: Mapped[str] = mapped_column(Text, default="[]")  # JSON list [{name, amount}]
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoadEvent(Base):
    """Audit trail: every state change / significant action, timestamped + attributed."""
    __tablename__ = "load_events"
    __table_args__ = (Index("ix_load_events_load", "load_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("loads.id"), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)  # STATE_CHANGE, COMPLIANCE_FLAG, OVERRIDE, RATE_CONFIRMED, POD, CREATED
    from_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    load: Mapped["Load"] = relationship(back_populates="events", foreign_keys=[load_id])
    actor: Mapped["User"] = relationship()
