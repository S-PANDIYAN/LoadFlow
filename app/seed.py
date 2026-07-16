"""Demo seed data — idempotent, runs at startup.

Creates: 1 broker org (admin + dispatcher + ops lead), 2 carrier orgs
(FastFreight = compliant; RustyWheels = EXPIRED insurance -> demos the
compliance block), 1 shipper, and sample loads in several states.
All demo passwords: demo1234
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.enums import AccountType, OrgType, LoadState, AuthorityStatus
from app.models import (
    Organization, User, Role, RolePermission, UserRole, Permission,
    CarrierCompliance, Load, LoadEvent,
)
from app.security import hash_password

logger = logging.getLogger("loadflow.seed")

DEMO_PASSWORD = "demo1234"


def seed_demo_data(db: Session):
    if db.query(Organization).first():
        return  # already seeded

    pw = hash_password(DEMO_PASSWORD)
    perms = {p.code: p for p in db.query(Permission).all()}

    def make_role(org_id, name, codes, creator_id):
        role = Role(organization_id=org_id, name=name, created_by=creator_id)
        db.add(role)
        db.flush()
        for c in codes:
            db.add(RolePermission(role_id=role.id, permission_id=perms[c].id))
        return role

    # --- Broker org ---
    broker = Organization(name="Apex Logistics", organization_type=OrgType.BROKER)
    db.add(broker)
    db.flush()
    b_admin = User(full_name="Bree Admin", email="broker.admin@demo.io", password_hash=pw,
                   account_type=AccountType.BROKER, organization_id=broker.id, is_org_admin=True)
    db.add(b_admin)
    db.flush()

    dispatcher_role = make_role(broker.id, "Dispatcher",
                                ["load.create", "load.assign_carrier", "rate.confirm",
                                 "load.update_status"], b_admin.id)
    ops_lead_role = make_role(broker.id, "Ops Lead",
                              ["load.create", "load.assign_carrier", "rate.confirm",
                               "load.update_status", "load.override_compliance_flag"], b_admin.id)

    b_dispatch = User(full_name="Dan Dispatcher", email="dispatcher@demo.io", password_hash=pw,
                      account_type=AccountType.BROKER, organization_id=broker.id)
    b_ops = User(full_name="Olivia OpsLead", email="opslead@demo.io", password_hash=pw,
                 account_type=AccountType.BROKER, organization_id=broker.id)
    db.add_all([b_dispatch, b_ops])
    db.flush()
    db.add_all([UserRole(user_id=b_dispatch.id, role_id=dispatcher_role.id),
                UserRole(user_id=b_ops.id, role_id=ops_lead_role.id)])

    # --- Carrier orgs ---
    fast = Organization(name="FastFreight Inc", organization_type=OrgType.CARRIER)
    rusty = Organization(name="RustyWheels Transport", organization_type=OrgType.CARRIER)
    db.add_all([fast, rusty])
    db.flush()

    f_admin = User(full_name="Fiona CarrierAdmin", email="carrier.admin@demo.io", password_hash=pw,
                   account_type=AccountType.CARRIER, organization_id=fast.id, is_org_admin=True)
    db.add(f_admin)
    db.flush()
    driver_role = make_role(fast.id, "Driver", ["load.update_status", "pod.upload"], f_admin.id)
    cdispatch_role = make_role(fast.id, "Carrier Dispatch",
                               ["load.accept", "load.decline", "load.update_status"], f_admin.id)
    f_driver = User(full_name="Diego Driver", email="driver@demo.io", password_hash=pw,
                    account_type=AccountType.CARRIER, organization_id=fast.id)
    f_cd = User(full_name="Cass CarrierDispatch", email="carrier.dispatch@demo.io", password_hash=pw,
                account_type=AccountType.CARRIER, organization_id=fast.id)
    db.add_all([f_driver, f_cd])
    db.flush()
    db.add_all([UserRole(user_id=f_driver.id, role_id=driver_role.id),
                UserRole(user_id=f_cd.id, role_id=cdispatch_role.id)])

    r_admin = User(full_name="Rusty Admin", email="rusty.admin@demo.io", password_hash=pw,
                   account_type=AccountType.CARRIER, organization_id=rusty.id, is_org_admin=True)
    db.add(r_admin)

    now = datetime.now(timezone.utc)
    db.add(CarrierCompliance(
        carrier_org_id=fast.id,
        insurance_expiry=now + timedelta(days=180),
        mc_number="MC-123456", dot_number="DOT-7890123",
        authority_status=AuthorityStatus.ACTIVE,
        approved_equipment="Dry Van, Reefer, Flatbed",
        approved_commodities="Electronics, Produce, General Freight",
    ))
    db.add(CarrierCompliance(
        carrier_org_id=rusty.id,
        insurance_expiry=now - timedelta(days=14),  # EXPIRED -> demos the block
        mc_number="MC-999111", dot_number="DOT-5551212",
        authority_status=AuthorityStatus.ACTIVE,
        approved_equipment="Dry Van",
        approved_commodities="General Freight",
    ))

    # --- Shipper ---
    shipper = User(full_name="Sam Shipper", email="shipper@demo.io", password_hash=pw,
                   account_type=AccountType.SHIPPER)
    db.add(shipper)
    db.flush()

    # --- Loads ---
    def make_load(ref, origin, dest, equip, comm, state, carrier_id=None,
                  flagged=False, reason=None):
        l = Load(reference=ref, origin=origin, destination=dest,
                 equipment_type=equip, commodity=comm, weight_lbs=42000,
                 pickup_date=now + timedelta(days=2),
                 state=state, shipper_id=shipper.id, broker_org_id=broker.id,
                 carrier_org_id=carrier_id, compliance_flagged=flagged,
                 compliance_reason=reason, created_by=b_dispatch.id)
        db.add(l)
        db.flush()
        db.add(LoadEvent(load_id=l.id, actor_id=b_dispatch.id, event_type="CREATED",
                         to_state=LoadState.POSTED.value, note="Seed data"))
        return l

    make_load("LF-00001", "Chicago, IL", "Dallas, TX", "Dry Van", "Electronics",
              LoadState.POSTED)
    make_load("LF-00002", "Atlanta, GA", "Miami, FL", "Reefer", "Produce",
              LoadState.CARRIER_ASSIGNED, carrier_id=fast.id)
    make_load("LF-00003", "Denver, CO", "Phoenix, AZ", "Dry Van", "General Freight",
              LoadState.IN_TRANSIT, carrier_id=fast.id)
    make_load("LF-00004", "Seattle, WA", "Portland, OR", "Dry Van", "General Freight",
              LoadState.CARRIER_ASSIGNED, carrier_id=rusty.id,
              flagged=True, reason="Insurance expired")

    db.commit()
    logger.info("Seeded demo data. All demo passwords: %s", DEMO_PASSWORD)
