"""Compliance evaluation service.

A load auto-flags when the assigned carrier has:
- expired (or missing) insurance
- non-ACTIVE MC/DOT authority
- equipment or commodity type not in the carrier's approved lists

The flag blocks progression past CARRIER_ASSIGNED until the compliance record
is fixed (re-checked on every transition) or explicitly overridden by a holder
of load.override_compliance_flag.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.enums import AuthorityStatus
from app.models import CarrierCompliance, Load


def _csv_contains(csv: str, value: str) -> bool:
    items = [x.strip().lower() for x in (csv or "").split(",") if x.strip()]
    return value.strip().lower() in items


def evaluate_carrier_compliance(db: Session, load: Load) -> list[str]:
    """Return list of violation reasons for the load's assigned carrier (empty = compliant)."""
    if load.carrier_org_id is None:
        return []
    rec = db.query(CarrierCompliance).filter_by(carrier_org_id=load.carrier_org_id).first()
    if rec is None:
        return ["No compliance record on file for carrier"]

    reasons = []
    now = datetime.now(timezone.utc)
    if rec.insurance_expiry is None:
        reasons.append("No insurance on file")
    else:
        exp = rec.insurance_expiry
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            reasons.append(f"Insurance expired {exp.date()}")
    if rec.authority_status != AuthorityStatus.ACTIVE:
        reasons.append(f"Authority status: {rec.authority_status.value}")
    if rec.approved_equipment and not _csv_contains(rec.approved_equipment, load.equipment_type):
        reasons.append(f"Equipment '{load.equipment_type}' not approved for carrier")
    if rec.approved_commodities and not _csv_contains(rec.approved_commodities, load.commodity):
        reasons.append(f"Commodity '{load.commodity}' not approved for carrier")
    return reasons


def refresh_compliance_flag(db: Session, load: Load) -> list[str]:
    """Re-evaluate and update the load's flag. Preserves an existing override
    only while the load stays flagged for the same carrier."""
    reasons = evaluate_carrier_compliance(db, load)
    if reasons:
        load.compliance_flagged = True
        load.compliance_reason = "; ".join(reasons)
    else:
        load.compliance_flagged = False
        load.compliance_reason = None
        load.compliance_overridden = False
    return reasons
