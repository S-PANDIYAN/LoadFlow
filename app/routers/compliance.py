"""Carrier compliance record CRUD.

Broker staff manage compliance records (the broker is liable for dispatching
non-compliant carriers, so brokers maintain vetting records). Carrier admins
can view their own record.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_account_type
from app.enums import AccountType, OrgType
from app.models import CarrierCompliance, Organization, User
from app.schemas import ComplianceUpsert, ComplianceOut

router = APIRouter(prefix="/compliance", tags=["compliance"])
logger = logging.getLogger("loadflow.compliance")


def _out(rec: CarrierCompliance, name: str | None = None) -> ComplianceOut:
    o = ComplianceOut.model_validate(rec)
    o.carrier_org_name = name or (rec.carrier_org.name if rec.carrier_org else None)
    return o


@router.get("/carriers", response_model=list[dict])
def list_carrier_orgs(user: User = Depends(require_account_type(AccountType.BROKER)),
                      db: Session = Depends(get_db)):
    """Broker directory of carrier orgs (for assignment + compliance mgmt),
    with expiry alert info (stretch #9)."""
    carriers = db.query(Organization).filter_by(organization_type=OrgType.CARRIER).all()
    soon = datetime.now(timezone.utc) + timedelta(days=30)
    result = []
    for c in carriers:
        rec = db.query(CarrierCompliance).filter_by(carrier_org_id=c.id).first()
        expiring = False
        expired = False
        if rec and rec.insurance_expiry:
            exp = rec.insurance_expiry
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            expired = exp < datetime.now(timezone.utc)
            expiring = (not expired) and exp < soon
        result.append({
            "id": c.id, "name": c.name,
            "has_compliance_record": rec is not None,
            "insurance_expired": expired,
            "insurance_expiring_soon": expiring,
            "authority_status": rec.authority_status.value if rec else None,
        })
    return result


@router.get("/carriers/{carrier_org_id}", response_model=ComplianceOut)
def get_compliance(carrier_org_id: int,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    # Org scoping: brokers can view any carrier's record (they vet carriers);
    # carrier staff can only view their OWN org's record.
    if user.account_type == AccountType.CARRIER and user.organization_id != carrier_org_id:
        logger.warning("SCOPE DENIED user=%s tried compliance of org=%s",
                       user.email, carrier_org_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if user.account_type == AccountType.SHIPPER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Shippers cannot view compliance records")
    rec = db.query(CarrierCompliance).filter_by(carrier_org_id=carrier_org_id).first()
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No compliance record")
    return _out(rec)


@router.put("/carriers/{carrier_org_id}", response_model=ComplianceOut)
def upsert_compliance(carrier_org_id: int, body: ComplianceUpsert,
                      user: User = Depends(require_account_type(AccountType.BROKER)),
                      db: Session = Depends(get_db)):
    """Broker staff create/update a carrier's compliance record."""
    org = db.get(Organization, carrier_org_id)
    if not org or org.organization_type != OrgType.CARRIER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carrier org not found")
    rec = db.query(CarrierCompliance).filter_by(carrier_org_id=carrier_org_id).first()
    if not rec:
        rec = CarrierCompliance(carrier_org_id=carrier_org_id)
        db.add(rec)
    rec.insurance_expiry = body.insurance_expiry
    rec.mc_number = body.mc_number
    rec.dot_number = body.dot_number
    rec.authority_status = body.authority_status
    rec.approved_equipment = body.approved_equipment
    rec.approved_commodities = body.approved_commodities
    db.commit()
    logger.info("COMPLIANCE UPDATED carrier=%s by=%s", org.name, user.email)
    return _out(rec, org.name)
