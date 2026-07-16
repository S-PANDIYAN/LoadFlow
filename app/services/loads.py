"""Object-level scoping + audit helpers for loads."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, Query

from app.enums import AccountType
from app.models import Load, LoadEvent, User


def scoped_loads_query(db: Session, user: User) -> Query:
    """THE object-level scoping rule (enforced at the query, not the UI):
    - Broker staff: loads belonging to their broker org
    - Carrier staff: only loads assigned to their carrier org (not the marketplace)
    - Shipper: only their own loads
    """
    q = db.query(Load)
    if user.account_type == AccountType.BROKER:
        return q.filter(Load.broker_org_id == user.organization_id)
    if user.account_type == AccountType.CARRIER:
        return q.filter(Load.carrier_org_id == user.organization_id)
    return q.filter(Load.shipper_id == user.id)


def get_scoped_load(db: Session, user: User, load_id: int) -> Load:
    """404 (not 403) for out-of-scope loads — don't leak existence."""
    load = scoped_loads_query(db, user).filter(Load.id == load_id).first()
    if not load:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Load not found")
    return load


def record_event(db: Session, load: Load, actor: User, event_type: str,
                 from_state: str | None = None, to_state: str | None = None,
                 note: str | None = None) -> None:
    """Append to the immutable audit trail — timestamped + attributed."""
    db.add(LoadEvent(
        load_id=load.id, actor_id=actor.id, event_type=event_type,
        from_state=from_state, to_state=to_state, note=note,
    ))
