"""RBAC management: permission catalog, org-scoped roles, staff, role assignment.

All endpoints are org-scoped: an admin can only manage roles/staff inside their
own organization (organization_id comes from the authenticated user, never from
client input).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import Permission, Role, RolePermission, User, UserRole
from app.schemas import (
    PermissionOut, RoleCreate, RoleOut, RoleUpdatePermissions,
    StaffCreate, AssignRole, UserOut,
)
from app.security import hash_password
from app.enums import AccountType

router = APIRouter(prefix="/rbac", tags=["rbac"])
logger = logging.getLogger("loadflow.rbac")


def _role_out(db: Session, role: Role) -> RoleOut:
    codes = [
        r[0] for r in db.query(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role.id).all()
    ]
    out = RoleOut.model_validate(role)
    out.permission_codes = sorted(codes)
    return out


def _get_org_role(db: Session, user: User, role_id: int) -> Role:
    """Fetch a role, enforcing org scoping — 404 if it belongs to another org."""
    role = db.get(Role, role_id)
    if not role or role.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The global permission catalog — visible to any authenticated user."""
    return db.query(Permission).order_by(Permission.code).all()


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(body: RoleCreate,
                user: User = Depends(require_permission("staff.manage")),
                db: Session = Depends(get_db)):
    if user.organization_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Shippers have no roles")
    if db.query(Role).filter(Role.organization_id == user.organization_id,
                             Role.name == body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Role name already exists in your org")

    role = Role(organization_id=user.organization_id, name=body.name, created_by=user.id)
    db.add(role)
    db.flush()

    perms = db.query(Permission).filter(Permission.code.in_(body.permission_codes)).all()
    for p in perms:
        db.add(RolePermission(role_id=role.id, permission_id=p.id))
    db.commit()
    logger.info("ROLE CREATED org=%s role=%s perms=%s by=%s",
                user.organization_id, role.name, body.permission_codes, user.email)
    return _role_out(db, role)


@router.get("/roles", response_model=list[RoleOut])
def list_roles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.organization_id is None:
        return []
    roles = db.query(Role).filter(Role.organization_id == user.organization_id).all()
    return [_role_out(db, r) for r in roles]


@router.put("/roles/{role_id}/permissions", response_model=RoleOut)
def set_role_permissions(role_id: int, body: RoleUpdatePermissions,
                         user: User = Depends(require_permission("staff.manage")),
                         db: Session = Depends(get_db)):
    role = _get_org_role(db, user, role_id)
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    perms = db.query(Permission).filter(Permission.code.in_(body.permission_codes)).all()
    for p in perms:
        db.add(RolePermission(role_id=role.id, permission_id=p.id))
    db.commit()
    logger.info("ROLE PERMS UPDATED role=%s perms=%s by=%s",
                role.name, body.permission_codes, user.email)
    return _role_out(db, role)


@router.post("/staff", response_model=UserOut, status_code=201)
def create_staff(body: StaffCreate,
                 user: User = Depends(require_permission("staff.manage")),
                 db: Session = Depends(get_db)):
    """Admin (or staff.manage holder) creates a staff account in THEIR org.
    This is the only way non-admin org accounts come to exist (invite flow)."""
    if user.organization_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Shippers cannot create staff")
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    staff = User(
        full_name=body.full_name,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        account_type=user.account_type,        # staff inherit org's account type
        organization_id=user.organization_id,  # org scoping: always creator's org
        is_org_admin=False,
    )
    db.add(staff)
    db.flush()

    for rid in body.role_ids:
        role = _get_org_role(db, user, rid)  # rejects cross-org role ids
        db.add(UserRole(user_id=staff.id, role_id=role.id))
    db.commit()
    logger.info("STAFF CREATED %s in org=%s by=%s", staff.email, user.organization_id, user.email)

    out = UserOut.model_validate(staff)
    out.organization_name = user.organization.name if user.organization else None
    return out


@router.get("/staff", response_model=list[UserOut])
def list_staff(user: User = Depends(require_permission("staff.manage")),
               db: Session = Depends(get_db)):
    staff = db.query(User).filter(User.organization_id == user.organization_id).all()
    result = []
    for s in staff:
        role_names = [
            r[0] for r in db.query(Role.name).join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == s.id).all()
        ]
        out = UserOut.model_validate(s)
        out.roles = role_names
        result.append(out)
    return result


@router.post("/assign-role", status_code=200)
def assign_role(body: AssignRole,
                user: User = Depends(require_permission("staff.manage")),
                db: Session = Depends(get_db)):
    target = db.get(User, body.user_id)
    if not target or target.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in your org")
    role = _get_org_role(db, user, body.role_id)
    if db.query(UserRole).filter_by(user_id=target.id, role_id=role.id).first():
        return {"ok": True, "detail": "Already assigned"}
    db.add(UserRole(user_id=target.id, role_id=role.id))
    db.commit()
    logger.info("ROLE ASSIGNED role=%s -> user=%s by=%s", role.name, target.email, user.email)
    return {"ok": True}
