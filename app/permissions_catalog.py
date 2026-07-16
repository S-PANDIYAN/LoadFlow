"""Permission catalog — fixed, global, immutable. Seeded at startup."""

PERMISSION_CATALOG = [
    ("load.create", "Post/create loads and edit load details"),
    ("load.assign_carrier", "Assign a carrier to a load"),
    ("load.override_compliance_flag", "Override a compliance flag on a load"),
    ("rate.confirm", "Create and confirm rate confirmation versions"),
    ("load.update_status", "Progress a load through its lifecycle states"),
    ("staff.manage", "Create staff accounts, roles, and assign roles"),
    ("pod.upload", "Upload/record proof of delivery"),
    ("load.accept", "Accept an assigned load (carrier side)"),
    ("load.decline", "Decline an assigned load (carrier side)"),
]


def seed_permissions(db):
    from app.models import Permission
    existing = {p.code for p in db.query(Permission).all()}
    for code, desc in PERMISSION_CATALOG:
        if code not in existing:
            db.add(Permission(code=code, description=desc))
    db.commit()
