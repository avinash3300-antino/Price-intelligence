"""Admin API: users, their permissions, their markets, and the audit trail.

Every route here requires role='admin'. The rules that protect the system from
its own administrators live in this module:

  * The owner cannot be demoted, deactivated or deleted.
  * An admin cannot strip their own admin role, so the last one standing
    cannot lock everyone out by accident.
  * Anything that changes what an account may do — deactivation, demotion, a
    password reset — ends that account's live sessions, because a permission
    change that only takes effect at next login is not a permission change.
"""
from __future__ import annotations

import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from backend.deps import client_ip, conn, require_admin
from src import auth

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ------------------------------------------------------------------ models


class PermissionOut(BaseModel):
    key: str
    label: str
    category: str
    description: str
    sort_order: int


class TemplateOut(BaseModel):
    id: int
    name: str
    description: str
    is_system: bool
    permissions: list[str]


class ScopeIn(BaseModel):
    country: str
    city: Optional[str] = None


class UserSummary(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    is_owner: bool
    must_change_password: bool
    template_name: Optional[str] = None
    permission_count: int
    scope_count: int
    created_at: str
    last_login_at: Optional[str] = None


class UserDetail(UserSummary):
    role_template_id: Optional[int] = None
    # What the user actually holds, after template + overrides.
    effective_permissions: list[str]
    # Only the deltas, so the editor can show which boxes were touched by hand.
    overrides: dict[str, bool]
    scopes: list[ScopeIn]


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1)
    role: str = "user"
    role_template_id: Optional[int] = None
    password: Optional[str] = None       # generated when omitted
    scopes: list[ScopeIn] = []
    overrides: dict[str, bool] = {}


class CreateUserResponse(BaseModel):
    id: int
    email: str
    # Shown once. Stored only as an argon2 hash, so it cannot be read back.
    temporary_password: str


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    role_template_id: Optional[int] = None


class ResetPasswordResponse(BaseModel):
    temporary_password: str


class AuditEntry(BaseModel):
    id: int
    actor_email: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    ip: Optional[str] = None
    created_at: str
    before_json: Optional[Any] = None
    after_json: Optional[Any] = None


# ----------------------------------------------------------------- helpers


def _load_user(c, user_id: int) -> dict[str, Any]:
    row = c.execute(
        """SELECT u.*, t.name AS template_name
           FROM users u
           LEFT JOIN role_templates t ON t.id = u.role_template_id
           WHERE u.id = %s""",
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row)


def _detail(c, user_id: int) -> UserDetail:
    u = _load_user(c, user_id)
    eff = sorted(auth.effective_permissions(c, u))
    overrides = {
        r["permission_key"]: r["granted"]
        for r in c.execute(
            "SELECT permission_key, granted FROM user_permissions WHERE user_id = %s",
            (user_id,),
        )
    }
    scopes = [ScopeIn(**s) for s in auth.get_scopes(c, user_id)]
    return UserDetail(
        id=u["id"], email=u["email"], full_name=u["full_name"], role=u["role"],
        is_active=u["is_active"], is_owner=u["is_owner"],
        must_change_password=u["must_change_password"],
        template_name=u["template_name"], role_template_id=u["role_template_id"],
        permission_count=len(eff), scope_count=len(scopes),
        created_at=u["created_at"], last_login_at=u["last_login_at"],
        effective_permissions=eff, overrides=overrides, scopes=scopes,
    )


def _guard_owner(target: dict[str, Any], what: str) -> None:
    if target["is_owner"]:
        raise HTTPException(
            status_code=400,
            detail=f"The owner account cannot be {what}. This is what keeps the "
                   f"system from being locked out of itself.",
        )


# ------------------------------------------------------------------- reads


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(admin: dict = Depends(require_admin)):
    with conn() as c:
        return [
            PermissionOut(**dict(r))
            for r in c.execute(
                "SELECT key, label, category, description, sort_order "
                "FROM permissions ORDER BY sort_order"
            )
        ]


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(admin: dict = Depends(require_admin)):
    with conn() as c:
        out: list[TemplateOut] = []
        for t in c.execute(
            "SELECT id, name, description, is_system FROM role_templates ORDER BY id"
        ):
            perms = [
                r["permission_key"]
                for r in c.execute(
                    "SELECT permission_key FROM role_template_permissions "
                    "WHERE template_id = %s",
                    (t["id"],),
                )
            ]
            out.append(TemplateOut(**dict(t), permissions=sorted(perms)))
        return out


@router.get("/markets")
def list_markets(admin: dict = Depends(require_admin)):
    """Countries and their cities, straight from the catalogue.

    The scope picker offers exactly what exists rather than a typed-in string,
    so a scope can never be assigned to a city with a typo in it.
    """
    with conn() as c:
        rows = c.execute(
            """SELECT country, city, COUNT(*) AS products
               FROM products
               WHERE country IS NOT NULL AND country <> ''
               GROUP BY country, city
               ORDER BY country, city"""
        ).fetchall()
    by_country: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = by_country.setdefault(
            r["country"], {"country": r["country"], "products": 0, "cities": []}
        )
        entry["products"] += r["products"]
        if r["city"]:
            entry["cities"].append({"city": r["city"], "products": r["products"]})
    return list(by_country.values())


@router.get("/users", response_model=list[UserSummary])
def list_users(
    q: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = Query(None, pattern="^(active|inactive)$"),
    admin: dict = Depends(require_admin),
):
    sql = """SELECT u.id, u.email, u.full_name, u.role, u.is_active, u.is_owner,
                    u.must_change_password, u.created_at, u.last_login_at,
                    u.role_template_id, t.name AS template_name,
                    (SELECT COUNT(*) FROM user_scopes s WHERE s.user_id = u.id) AS scope_count
             FROM users u
             LEFT JOIN role_templates t ON t.id = u.role_template_id
             WHERE TRUE"""
    args: list[Any] = []
    if q:
        sql += " AND (LOWER(u.email) LIKE %s OR LOWER(u.full_name) LIKE %s)"
        needle = f"%{q.strip().lower()}%"
        args.extend([needle, needle])
    if role:
        sql += " AND u.role = %s"
        args.append(role)
    if status:
        sql += " AND u.is_active = %s"
        args.append(status == "active")
    sql += " ORDER BY u.is_owner DESC, u.role, LOWER(u.email)"

    with conn() as c:
        rows = c.execute(sql, args).fetchall()
        out: list[UserSummary] = []
        for r in rows:
            d = dict(r)
            d["permission_count"] = len(auth.effective_permissions(c, d))
            out.append(UserSummary(**{k: d[k] for k in UserSummary.model_fields}))
        return out


@router.get("/users/{user_id}", response_model=UserDetail)
def get_user(user_id: int, admin: dict = Depends(require_admin)):
    with conn() as c:
        return _detail(c, user_id)


@router.get("/audit", response_model=list[AuditEntry])
def list_audit(
    limit: int = Query(100, le=500),
    actor: Optional[str] = None,
    action: Optional[str] = None,
    admin: dict = Depends(require_admin),
):
    sql = "SELECT * FROM audit_log WHERE TRUE"
    args: list[Any] = []
    if actor:
        sql += " AND LOWER(actor_email) LIKE %s"
        args.append(f"%{actor.strip().lower()}%")
    if action:
        sql += " AND action LIKE %s"
        args.append(f"{action}%")
    sql += " ORDER BY id DESC LIMIT %s"
    args.append(limit)
    with conn() as c:
        return [AuditEntry(**dict(r)) for r in c.execute(sql, args)]


# ------------------------------------------------------------------ writes


@router.post("/users", response_model=CreateUserResponse, status_code=201)
def create_user(req: CreateUserRequest, request: Request,
                admin: dict = Depends(require_admin)):
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")

    password = req.password or secrets.token_urlsafe(9)
    problem = auth.password_problem(password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    email = str(req.email).strip().lower()
    with conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
            raise HTTPException(status_code=409, detail=f"{email} already has an account.")

        row = c.execute(
            """INSERT INTO users (email, password_hash, full_name, role, is_active,
                                  must_change_password, role_template_id,
                                  created_by, created_at)
               VALUES (%s, %s, %s, %s, TRUE, TRUE, %s, %s, %s)
               RETURNING id""",
            (email, auth.hash_password(password), req.full_name.strip(), req.role,
             req.role_template_id, admin["id"], auth.now_iso()),
        ).fetchone()
        uid = row["id"]

        for s in req.scopes:
            c.execute(
                "INSERT INTO user_scopes (user_id, country, city) VALUES (%s, %s, %s)",
                (uid, s.country, s.city),
            )
        for key, granted in req.overrides.items():
            c.execute(
                "INSERT INTO user_permissions (user_id, permission_key, granted) "
                "VALUES (%s, %s, %s)",
                (uid, key, granted),
            )

        auth.audit(
            c, admin, "user.created", "user", uid,
            after={"email": email, "role": req.role,
                   "template_id": req.role_template_id,
                   "scopes": [s.model_dump() for s in req.scopes],
                   "overrides": req.overrides},
            ip=client_ip(request),
        )
        c.commit()

    return CreateUserResponse(id=uid, email=email, temporary_password=password)


@router.patch("/users/{user_id}", response_model=UserDetail)
def update_user(user_id: int, req: UpdateUserRequest, request: Request,
                admin: dict = Depends(require_admin)):
    with conn() as c:
        target = _load_user(c, user_id)
        before = {k: target[k] for k in ("full_name", "role", "is_active", "role_template_id")}

        if req.role is not None and req.role != target["role"]:
            _guard_owner(target, "demoted or promoted")
            if user_id == admin["id"] and req.role != "admin":
                raise HTTPException(
                    status_code=400,
                    detail="You cannot remove your own admin role.",
                )
            if req.role not in ("admin", "user"):
                raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")

        if req.is_active is not None and req.is_active != target["is_active"]:
            _guard_owner(target, "deactivated")
            if user_id == admin["id"] and not req.is_active:
                raise HTTPException(
                    status_code=400, detail="You cannot deactivate your own account."
                )

        sets, args = [], []
        for field in ("full_name", "role", "is_active", "role_template_id"):
            value = getattr(req, field)
            if value is not None:
                sets.append(f"{field} = %s")
                args.append(value.strip() if field == "full_name" else value)
        if sets:
            args.append(user_id)
            c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", args)

        # A change to role or activation must not wait for the next login.
        if (req.role is not None and req.role != target["role"]) or (
            req.is_active is not None and req.is_active != target["is_active"]
        ):
            auth.revoke_all_sessions(c, user_id)

        auth.audit(c, admin, "user.updated", "user", user_id,
                   before=before, after=req.model_dump(exclude_none=True),
                   ip=client_ip(request))
        c.commit()
        return _detail(c, user_id)


@router.put("/users/{user_id}/permissions", response_model=UserDetail)
def set_permissions(user_id: int, overrides: dict[str, bool], request: Request,
                    admin: dict = Depends(require_admin)):
    """Replace this user's overrides wholesale.

    The payload is the full override set, not a patch — the editor sends what
    it shows, so a permission removed from the payload stops being an override
    and falls back to whatever the template says.
    """
    with conn() as c:
        _load_user(c, user_id)
        valid = {r["key"] for r in c.execute("SELECT key FROM permissions")}
        unknown = set(overrides) - valid
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"Unknown permissions: {', '.join(sorted(unknown))}"
            )
        before = {
            r["permission_key"]: r["granted"]
            for r in c.execute(
                "SELECT permission_key, granted FROM user_permissions WHERE user_id = %s",
                (user_id,),
            )
        }
        c.execute("DELETE FROM user_permissions WHERE user_id = %s", (user_id,))
        for key, granted in overrides.items():
            c.execute(
                "INSERT INTO user_permissions (user_id, permission_key, granted) "
                "VALUES (%s, %s, %s)",
                (user_id, key, granted),
            )
        auth.audit(c, admin, "user.permissions_set", "user", user_id,
                   before=before, after=overrides, ip=client_ip(request))
        c.commit()
        return _detail(c, user_id)


@router.put("/users/{user_id}/scopes", response_model=UserDetail)
def set_scopes(user_id: int, scopes: list[ScopeIn], request: Request,
               admin: dict = Depends(require_admin)):
    """Replace this user's markets wholesale.

    An empty list means no access to anything, which is a legitimate state —
    it is how you park an account without deactivating it.
    """
    with conn() as c:
        _load_user(c, user_id)
        before = auth.get_scopes(c, user_id)
        c.execute("DELETE FROM user_scopes WHERE user_id = %s", (user_id,))
        seen: set[tuple[str, Optional[str]]] = set()
        for s in scopes:
            key = (s.country, s.city)
            if key in seen:
                continue
            seen.add(key)
            c.execute(
                "INSERT INTO user_scopes (user_id, country, city) VALUES (%s, %s, %s)",
                (user_id, s.country, s.city),
            )
        auth.audit(c, admin, "user.scopes_set", "user", user_id,
                   before=before, after=[s.model_dump() for s in scopes],
                   ip=client_ip(request))
        c.commit()
        return _detail(c, user_id)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_password(user_id: int, request: Request,
                   admin: dict = Depends(require_admin)):
    """Issue a new temporary password and end the account's sessions.

    Returned once, in the response. Nothing stores it in the clear, so losing
    it means resetting again rather than looking it up.
    """
    password = secrets.token_urlsafe(9)
    with conn() as c:
        _load_user(c, user_id)
        c.execute(
            "UPDATE users SET password_hash = %s, must_change_password = TRUE WHERE id = %s",
            (auth.hash_password(password), user_id),
        )
        auth.revoke_all_sessions(c, user_id)
        auth.audit(c, admin, "user.password_reset", "user", user_id,
                   ip=client_ip(request))
        c.commit()
    return ResetPasswordResponse(temporary_password=password)


class DeleteImpactResponse(BaseModel):
    """What permanently deleting this account would cost."""
    email: str
    mappings: int
    competitors: int
    listings: int
    audit_entries: int


@router.get("/users/{user_id}/delete-impact", response_model=DeleteImpactResponse)
def delete_impact(user_id: int, admin: dict = Depends(require_admin)):
    """Count the work attributed to this account.

    The UI shows this before offering permanent deletion, so the decision is
    made knowing what authorship is about to be lost rather than after.
    """
    with conn() as c:
        target = _load_user(c, user_id)
        def n(sql: str) -> int:
            return next(iter(c.execute(sql, (user_id,)).fetchone().values()))
        return DeleteImpactResponse(
            email=target["email"],
            mappings=n("SELECT COUNT(*) FROM mappings WHERE created_by = %s"),
            competitors=n("SELECT COUNT(*) FROM competitors WHERE created_by = %s"),
            listings=n("SELECT COUNT(*) FROM competitor_listings WHERE created_by = %s"),
            audit_entries=n("SELECT COUNT(*) FROM audit_log WHERE actor_user_id = %s"),
        )


@router.delete("/users/{user_id}/permanent", status_code=204)
def delete_user_permanently(user_id: int, request: Request,
                            admin: dict = Depends(require_admin)):
    """Remove the account row entirely.

    Deactivation is the better answer almost always, and the UI says so. This
    exists for accounts created in error, or where a record must genuinely be
    erased.

    What survives: the audit log. actor_email is denormalised, so every action
    they took is still attributed to the address that took it, including this
    deletion.

    What is lost: created_by on their mappings, competitors and listings goes
    NULL. The work itself is untouched — only the record of who produced it.
    That is the whole reason deactivation is offered first.
    """
    with conn() as c:
        target = _load_user(c, user_id)
        _guard_owner(target, "deleted")
        if user_id == admin["id"]:
            raise HTTPException(
                status_code=400, detail="You cannot delete your own account."
            )

        counts = {}
        for table in ("mappings", "competitors", "competitor_listings"):
            counts[table] = next(iter(c.execute(
                f"SELECT COUNT(*) FROM {table} WHERE created_by = %s", (user_id,)
            ).fetchone().values()))

        # Audited before the row disappears, so the entry can still name what
        # was removed and what it cost.
        auth.audit(
            c, admin, "user.deleted_permanently", "user", user_id,
            before={
                "email": target["email"],
                "full_name": target["full_name"],
                "role": target["role"],
                "orphaned_attribution": counts,
            },
            ip=client_ip(request),
        )

        # Release every reference before removing the row. user_scopes,
        # user_permissions and sessions cascade; these three and the audit log
        # do not, deliberately — silently cascading a delete into mappings
        # would destroy real work.
        for table in ("mappings", "competitors", "competitor_listings"):
            c.execute(f"UPDATE {table} SET created_by = NULL WHERE created_by = %s",
                      (user_id,))
        c.execute("UPDATE audit_log SET actor_user_id = NULL WHERE actor_user_id = %s",
                  (user_id,))
        c.execute("UPDATE users SET created_by = NULL WHERE created_by = %s", (user_id,))
        c.execute("DELETE FROM users WHERE id = %s", (user_id,))
        c.commit()
    return None


@router.delete("/users/{user_id}", status_code=204)
def deactivate_user(user_id: int, request: Request,
                    admin: dict = Depends(require_admin)):
    """Deactivate, never delete.

    Their mappings stay attributed to them, so the history of who did what
    survives the person leaving.
    """
    with conn() as c:
        target = _load_user(c, user_id)
        _guard_owner(target, "deactivated")
        if user_id == admin["id"]:
            raise HTTPException(
                status_code=400, detail="You cannot deactivate your own account."
            )
        c.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (user_id,))
        auth.revoke_all_sessions(c, user_id)
        auth.audit(c, admin, "user.deactivated", "user", user_id,
                   before={"email": target["email"], "is_active": True},
                   ip=client_ip(request))
        c.commit()
    return None
