"""Auth: registration (bootstrap), login, current profile.

Bootstrap rule (per spec): registering a Broker/Carrier org creates the org AND
its first Admin in one step. Staff accounts are only ever created by an admin
via /staff (see rbac router) — never by self-registration. Shippers are
standalone accounts with no org.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_user_permissions
from app.enums import AccountType, OrgType
from app.models import Organization, User, UserRole, Role
from app.schemas import OrgRegister, ShipperRegister, LoginRequest, TokenResponse, UserOut
from app.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("loadflow.auth")


def _email_taken(db: Session, email: str) -> bool:
    return db.query(User).filter(User.email == email.lower()).first() is not None


def _register_org(db: Session, body: OrgRegister, org_type: OrgType,
                  account_type: AccountType) -> TokenResponse:
    if _email_taken(db, body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if db.query(Organization).filter(Organization.name == body.organization_name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Organization name already taken")

    org = Organization(name=body.organization_name, organization_type=org_type)
    db.add(org)
    db.flush()

    admin = User(
        full_name=body.full_name,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        account_type=account_type,
        organization_id=org.id,
        is_org_admin=True,  # bootstrap: first account is the org admin/owner
    )
    db.add(admin)
    db.commit()

    token = create_access_token(
        user_id=admin.id, account_type=account_type.value,
        organization_id=org.id, is_org_admin=True,
    )
    logger.info("REGISTERED %s org=%s admin=%s", org_type.value, org.name, admin.email)
    return TokenResponse(access_token=token, account_type=account_type, is_org_admin=True)


@router.post("/register-broker", response_model=TokenResponse, status_code=201)
def register_broker(body: OrgRegister, db: Session = Depends(get_db)):
    return _register_org(db, body, OrgType.BROKER, AccountType.BROKER)


@router.post("/register-carrier", response_model=TokenResponse, status_code=201)
def register_carrier(body: OrgRegister, db: Session = Depends(get_db)):
    return _register_org(db, body, OrgType.CARRIER, AccountType.CARRIER)


@router.post("/register-shipper", response_model=TokenResponse, status_code=201)
def register_shipper(body: ShipperRegister, db: Session = Depends(get_db)):
    if _email_taken(db, body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    shipper = User(
        full_name=body.full_name,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        account_type=AccountType.SHIPPER,
        organization_id=None,
        is_org_admin=False,
    )
    db.add(shipper)
    db.commit()
    token = create_access_token(
        user_id=shipper.id, account_type=AccountType.SHIPPER.value,
        organization_id=None, is_org_admin=False,
    )
    logger.info("REGISTERED SHIPPER %s", shipper.email)
    return TokenResponse(access_token=token, account_type=AccountType.SHIPPER, is_org_admin=False)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        logger.warning("LOGIN FAILED email=%s", body.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.is_active:
        logger.warning("LOGIN BLOCKED inactive user=%s", body.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account deactivated")

    token = create_access_token(
        user_id=user.id, account_type=user.account_type.value,
        organization_id=user.organization_id, is_org_admin=user.is_org_admin,
    )
    # Cookie for the server-rendered UI; Bearer header also accepted by APIs.
    response.set_cookie("access_token", token, httponly=True, samesite="lax")
    logger.info("LOGIN OK user=%s", user.email)
    return TokenResponse(access_token=token, account_type=user.account_type,
                         is_org_admin=user.is_org_admin)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = sorted(get_user_permissions(db, user))
    role_names = [
        r[0] for r in db.query(Role.name).join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id).all()
    ]
    out = UserOut.model_validate(user)
    out.permissions = perms
    out.roles = role_names
    out.organization_name = user.organization.name if user.organization else None
    return out
