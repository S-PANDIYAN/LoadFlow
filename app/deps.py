"""Authorization dependencies — THE enforcement layer.

Design rules (per spec):
- Code checks PERMISSION CODES, never role names.
- Permissions are aggregated across all of a user's roles, read from DB at
  request time (role edits take effect immediately, not at next login).
- Org admins implicitly hold all catalog permissions within their own org.
- Org scoping and object scoping are enforced independently of permissions.
- Every denial returns 403 and is logged.
"""
import logging

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import AccountType
from app.models import User, Role, RolePermission, Permission, UserRole
from app.security import verify_token

logger = logging.getLogger("loadflow.authz")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # Fallback: cookie (used by the server-rendered UI)
    return request.cookies.get("access_token")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = verify_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    return user


def get_user_permissions(db: Session, user: User) -> set[str]:
    """Aggregate permission codes across all roles. Org admins get the full
    catalog (within their org — org scoping is enforced separately)."""
    if user.is_org_admin:
        return {p.code for p in db.query(Permission).all()}
    rows = (
        db.query(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id)
        .all()
    )
    return {r[0] for r in rows}


def require_permission(permission_code: str):
    """Dependency factory: 403 + log when the user lacks the permission."""
    def checker(request: Request,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> User:
        perms = get_user_permissions(db, user)
        if permission_code not in perms:
            logger.warning(
                "PERMISSION DENIED user=%s (%s) needed=%s path=%s",
                user.email, user.account_type.value, permission_code, request.url.path,
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Missing permission: {permission_code}",
            )
        return user
    return checker


def require_account_type(*types: AccountType):
    """Dependency factory: restrict an endpoint to given account types."""
    def checker(request: Request, user: User = Depends(get_current_user)) -> User:
        if user.account_type not in types:
            logger.warning(
                "ACCOUNT-TYPE DENIED user=%s type=%s allowed=%s path=%s",
                user.email, user.account_type.value,
                [t.value for t in types], request.url.path,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for this account type")
        return user
    return checker


def require_org_admin(request: Request, user: User = Depends(get_current_user)) -> User:
    if not user.is_org_admin or user.organization_id is None:
        logger.warning("ADMIN DENIED user=%s path=%s", user.email, request.url.path)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Org admin only")
    return user
