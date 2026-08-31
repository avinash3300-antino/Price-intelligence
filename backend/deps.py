"""Request-scoped dependencies: database handle, current user, permission gates.

Enforcement is server-side and lives here. The UI hiding a button is a
courtesy; this module is what actually decides.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Optional

import psycopg
from fastapi import Depends, HTTPException, Request

from src import auth, db

# Endpoints reachable while a user still owes a password change. Everything
# else is refused until they set one, so a handed-over temporary password
# cannot be used to do actual work.
PASSWORD_CHANGE_EXEMPT = {
    "/api/auth/me",
    "/api/auth/change-password",
    "/api/auth/logout",
    "/api/health",
}


@contextmanager
def conn():
    """One Postgres connection per use.

    Autocommit stays off so multi-statement writes are atomic — the manual
    mapping endpoint deletes a prior mapping then inserts a replacement, and
    those must land together. Write paths commit explicitly; read paths close,
    which rolls back the empty transaction.
    """
    try:
        c = db.get_conn()
    except psycopg.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}") from e
    try:
        yield c
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def client_ip(request: Request) -> Optional[str]:
    """Real client address behind nginx, which sets X-Forwarded-For."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def get_current_user(request: Request) -> dict[str, Any]:
    """Resolve the session cookie to a user, or 401.

    Also attaches the effective permission set so downstream gates do not each
    re-derive it, and refuses anything but the password-change flow while
    must_change_password is set.
    """
    token = request.cookies.get(auth.SESSION_COOKIE)
    with conn() as c:
        user = auth.resolve_session(c, token)
        if not user:
            raise HTTPException(status_code=401, detail="Not signed in")
        user["permissions"] = sorted(auth.effective_permissions(c, user))
        user["scopes"] = auth.get_scopes(c, user["id"])

    if user["must_change_password"] and request.url.path not in PASSWORD_CHANGE_EXEMPT:
        raise HTTPException(
            status_code=403,
            detail="password_change_required",
        )
    return user


def require(*permission_keys: str) -> Callable[..., dict[str, Any]]:
    """Dependency factory gating an endpoint on one or more permissions.

    Admins pass everything — effective_permissions() already returns the full
    catalogue for them, so no special case is needed here.
    """
    def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        held = set(user["permissions"])
        missing = [k for k in permission_keys if k not in held]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {', '.join(missing)}",
            )
        return user
    return _dep


def require_any(*permission_keys: str) -> Callable[..., dict[str, Any]]:
    """Like require(), but the user needs only one of the listed permissions.

    Used where a single endpoint feeds several screens — /api/dashboard backs
    both the mapping workspace and the portfolio view, and a user entitled to
    either should be able to load it.
    """
    def _dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if not set(permission_keys) & set(user["permissions"]):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {', '.join(permission_keys)}",
            )
        return user
    return _dep


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def assert_product_in_scope(c, user: dict[str, Any], product_id: int) -> None:
    """404, not 403, when a product is outside the user's scope.

    Out of scope means hidden, and a 403 would confirm the product exists —
    which is the one thing hiding is supposed to prevent.
    """
    if not auth.product_in_scope(c, user, product_id):
        raise HTTPException(status_code=404, detail="Product not found")


def assert_option_in_scope(c, user: dict[str, Any], option_id: int) -> int:
    """Same, addressed by option. Returns the anchor product id."""
    pid = auth.product_id_for_option(c, option_id)
    if pid is None:
        raise HTTPException(status_code=404, detail="Option not found")
    assert_product_in_scope(c, user, pid)
    return pid
