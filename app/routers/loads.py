"""Loads: CRUD, carrier assignment, state machine, compliance flag/override,
rate confirmation versioning, POD, audit trail.

Every endpoint enforces: permission (require_permission) + org scoping +
object-level scoping (scoped queries). Transitions are validated server-side
against LOAD_TRANSITIONS, and compliance-flagged loads cannot progress past
CARRIER_ASSIGNED unless overridden.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission, get_user_permissions
from app.enums import AccountType, LoadState, OrgType, LOAD_TRANSITIONS, STATES_REQUIRING_COMPLIANCE
from app.models import Load, Organization, RateConfirmation, User
from app.schemas import (
    LoadCreate, LoadOut, AssignCarrier, TransitionRequest, OverrideRequest,
    RateConfCreate, RateConfOut, PodRequest, LoadEventOut,
)
from app.services.compliance import refresh_compliance_flag
from app.services.loads import scoped_loads_query, get_scoped_load, record_event

router = APIRouter(prefix="/loads", tags=["loads"])
logger = logging.getLogger("loadflow.loads")


def _load_out(load: Load) -> LoadOut:
    out = LoadOut.model_validate(load)
    out.shipper_name = load.shipper.full_name if load.shipper else None
    out.carrier_org_name = load.carrier_org.name if load.carrier_org else None
    return out


# ---- CRUD ----

@router.post("", response_model=LoadOut, status_code=201)
def create_load(body: LoadCreate,
                user: User = Depends(require_permission("load.create")),
                db: Session = Depends(get_db)):
    if user.account_type != AccountType.BROKER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only broker staff post loads")
    shipper = db.query(User).filter(User.email == body.shipper_email.lower(),
                                    User.account_type == AccountType.SHIPPER).first()
    if not shipper:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No shipper account with that email")

    count = db.query(Load).count()
    load = Load(
        reference=f"LF-{count + 1:05d}",
        origin=body.origin, destination=body.destination,
        equipment_type=body.equipment_type, commodity=body.commodity,
        weight_lbs=body.weight_lbs, pickup_date=body.pickup_date,
        shipper_id=shipper.id, broker_org_id=user.organization_id,
        created_by=user.id,
    )
    db.add(load)
    db.flush()
    record_event(db, load, user, "CREATED", to_state=LoadState.POSTED.value,
                 note=f"Load posted for shipper {shipper.full_name}")
    db.commit()
    return _load_out(load)


@router.get("", response_model=list[LoadOut])
def list_loads(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: str | None = QueryParam(None, description="search origin/destination/reference/commodity"),
    state: LoadState | None = None,
    carrier_org_id: int | None = None,
    flagged: bool | None = None,
):
    """Scoped list + broker load-board search/filter."""
    query = scoped_loads_query(db, user)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Load.origin.ilike(like), Load.destination.ilike(like),
            Load.reference.ilike(like), Load.commodity.ilike(like),
        ))
    if state:
        query = query.filter(Load.state == state)
    if carrier_org_id:
        query = query.filter(Load.carrier_org_id == carrier_org_id)
    if flagged is not None:
        query = query.filter(Load.compliance_flagged == flagged)
    return [_load_out(l) for l in query.order_by(Load.created_at.desc()).all()]


@router.get("/{load_id}", response_model=LoadOut)
def get_load(load_id: int, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    return _load_out(get_scoped_load(db, user, load_id))


@router.get("/{load_id}/events", response_model=list[LoadEventOut])
def load_audit_trail(load_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)
    result = []
    for e in load.events:
        out = LoadEventOut.model_validate(e)
        out.actor_name = e.actor.full_name if e.actor else None
        result.append(out)
    return result


# ---- Carrier assignment + compliance ----

@router.post("/{load_id}/assign-carrier", response_model=LoadOut)
def assign_carrier(load_id: int, body: AssignCarrier,
                   user: User = Depends(require_permission("load.assign_carrier")),
                   db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)
    if load.state != LoadState.POSTED:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Cannot assign carrier while load is {load.state.value}")
    carrier = db.get(Organization, body.carrier_org_id)
    if not carrier or carrier.organization_type != OrgType.CARRIER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carrier org not found")

    load.carrier_org_id = carrier.id
    load.compliance_overridden = False
    load.state = LoadState.CARRIER_ASSIGNED
    record_event(db, load, user, "STATE_CHANGE",
                 from_state=LoadState.POSTED.value, to_state=LoadState.CARRIER_ASSIGNED.value,
                 note=f"Assigned carrier {carrier.name}")

    # Auto-flag on assignment (spec: compliance check at assignment time)
    reasons = refresh_compliance_flag(db, load)
    if reasons:
        record_event(db, load, user, "COMPLIANCE_FLAG", note="; ".join(reasons))
        logger.warning("COMPLIANCE FLAG load=%s carrier=%s reasons=%s",
                       load.reference, carrier.name, reasons)
    db.commit()
    return _load_out(load)


@router.post("/{load_id}/override-compliance", response_model=LoadOut)
def override_compliance(load_id: int, body: OverrideRequest,
                        user: User = Depends(require_permission("load.override_compliance_flag")),
                        db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)
    if not load.compliance_flagged:
        raise HTTPException(status.HTTP_409_CONFLICT, "Load is not compliance-flagged")
    load.compliance_overridden = True
    record_event(db, load, user, "OVERRIDE",
                 note=f"Compliance flag overridden: {body.note}")
    logger.warning("COMPLIANCE OVERRIDE load=%s by=%s note=%s",
                   load.reference, user.email, body.note)
    db.commit()
    return _load_out(load)


# ---- State machine ----

TRANSITION_PERMISSION: dict[LoadState, str] = {
    # who may push INTO each state
    LoadState.RATE_CONFIRMED: "rate.confirm",
    LoadState.DISPATCHED: "load.update_status",
    LoadState.IN_TRANSIT: "load.update_status",
    LoadState.DELIVERED: "load.update_status",
    LoadState.POD_VERIFIED: "load.update_status",
    LoadState.CLOSED: "load.update_status",
    LoadState.POSTED: "load.update_status",  # unassign/decline path
}


@router.post("/{load_id}/transition", response_model=LoadOut)
def transition(load_id: int, body: TransitionRequest,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)
    target = body.to_state

    # 1. Legal transition?
    if target not in LOAD_TRANSITIONS.get(load.state, []):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Illegal transition {load.state.value} -> {target.value}",
        )

    # 2. Permission for the target state (checked by CODE, never role name)
    needed = TRANSITION_PERMISSION.get(target)
    perms = get_user_permissions(db, user)
    if needed and needed not in perms:
        logger.warning("PERMISSION DENIED user=%s needed=%s transition=%s->%s load=%s",
                       user.email, needed, load.state.value, target.value, load.reference)
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {needed}")

    # 3. Rate confirmation must exist & be confirmed before RATE_CONFIRMED
    if target == LoadState.RATE_CONFIRMED and load.rate_confirmation_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "No confirmed rate confirmation on this load")

    # 4. Compliance gate: re-check, then block past CARRIER_ASSIGNED
    if target in STATES_REQUIRING_COMPLIANCE:
        reasons = refresh_compliance_flag(db, load)
        if load.compliance_flagged and not load.compliance_overridden:
            db.commit()  # persist refreshed flag state
            logger.warning("COMPLIANCE BLOCK load=%s -> %s reasons=%s",
                           load.reference, target.value, reasons)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Blocked by compliance flag: {load.compliance_reason}. "
                "Resolve the carrier's compliance record or override.",
            )

    prev = load.state
    load.state = target
    if target == LoadState.POSTED:  # unassigned / declined
        load.carrier_org_id = None
        load.compliance_flagged = False
        load.compliance_reason = None
        load.compliance_overridden = False
    record_event(db, load, user, "STATE_CHANGE",
                 from_state=prev.value, to_state=target.value, note=body.note)
    db.commit()
    return _load_out(load)


# ---- Carrier accept/decline ----

@router.post("/{load_id}/accept", response_model=LoadOut)
def accept_load(load_id: int,
                user: User = Depends(require_permission("load.accept")),
                db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)  # carrier scoping: must be assigned to their org
    if load.state != LoadState.CARRIER_ASSIGNED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Load is not awaiting acceptance")
    record_event(db, load, user, "ACCEPTED", note="Carrier accepted the load")
    db.commit()
    return _load_out(load)


@router.post("/{load_id}/decline", response_model=LoadOut)
def decline_load(load_id: int,
                 user: User = Depends(require_permission("load.decline")),
                 db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)
    if load.state != LoadState.CARRIER_ASSIGNED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Load is not awaiting acceptance")
    prev = load.state
    load.state = LoadState.POSTED
    load.carrier_org_id = None
    load.compliance_flagged = False
    load.compliance_reason = None
    load.compliance_overridden = False
    record_event(db, load, user, "DECLINED",
                 from_state=prev.value, to_state=LoadState.POSTED.value,
                 note="Carrier declined; load back on the board")
    db.commit()
    return _load_out(load)


# ---- Rate confirmation (versioned) ----

@router.post("/{load_id}/rate-confirmations", response_model=RateConfOut, status_code=201)
def create_rate_confirmation(load_id: int, body: RateConfCreate,
                             user: User = Depends(require_permission("rate.confirm")),
                             db: Session = Depends(get_db)):
    """Create a NEW version (immutable). Re-negotiation = another version."""
    load = get_scoped_load(db, user, load_id)
    if load.carrier_org_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Assign a carrier before rating")
    last = (db.query(RateConfirmation).filter_by(load_id=load.id)
            .order_by(RateConfirmation.version.desc()).first())
    rc = RateConfirmation(
        load_id=load.id,
        version=(last.version + 1) if last else 1,
        base_rate=body.base_rate,
        accessorials=json.dumps(body.accessorials),
        created_by=user.id,
    )
    db.add(rc)
    db.flush()
    record_event(db, load, user, "RATE_VERSION",
                 note=f"Rate confirmation v{rc.version}: ${body.base_rate:,.2f}")
    db.commit()
    return rc


@router.post("/{load_id}/rate-confirmations/{version}/confirm", response_model=RateConfOut)
def confirm_rate(load_id: int, version: int,
                 user: User = Depends(require_permission("rate.confirm")),
                 db: Session = Depends(get_db)):
    """Confirm a specific version — the load keeps THIS version forever,
    even if later versions are created."""
    load = get_scoped_load(db, user, load_id)
    rc = db.query(RateConfirmation).filter_by(load_id=load.id, version=version).first()
    if not rc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rate confirmation version not found")
    rc.confirmed = True
    rc.confirmed_by = user.id
    rc.confirmed_at = datetime.now(timezone.utc)
    load.rate_confirmation_id = rc.id
    record_event(db, load, user, "RATE_CONFIRMED",
                 note=f"Confirmed rate v{rc.version} (${rc.base_rate:,.2f})")
    db.commit()
    return rc


@router.get("/{load_id}/rate-confirmations", response_model=list[RateConfOut])
def list_rate_confirmations(load_id: int,
                            user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)
    return (db.query(RateConfirmation).filter_by(load_id=load.id)
            .order_by(RateConfirmation.version).all())


# ---- POD (stretch, cheap stub) ----

@router.post("/{load_id}/pod", response_model=LoadOut)
def upload_pod(load_id: int, body: PodRequest,
               user: User = Depends(require_permission("pod.upload")),
               db: Session = Depends(get_db)):
    load = get_scoped_load(db, user, load_id)
    if load.state not in (LoadState.DELIVERED, LoadState.POD_VERIFIED):
        raise HTTPException(status.HTTP_409_CONFLICT, "POD only after delivery")
    load.pod_uploaded = True
    load.pod_note = body.note
    record_event(db, load, user, "POD", note=body.note or "POD uploaded")
    db.commit()
    return _load_out(load)
