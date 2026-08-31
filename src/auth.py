"""Authentication, permissions and data scope.

This module owns the rules; the API layer owns applying them. Nothing here
touches FastAPI, so the logic is testable without a request.

Three ideas:

* **Permissions are per-action.** A user's effective set is their template's
  permissions, plus per-user grants, minus per-user revokes. Admins short-
  circuit the whole calculation and hold everything.

* **Scope is country + city, and it hides rather than disables.** A user with
  no scope rows sees nothing. That default is deliberate: a new account should
  start with no access and be granted it, not start with everything and have
  it taken away.

* **Sessions live server-side.** The cookie carries a random token; the
  database stores only its SHA-256, so a leaked dump does not hand over live
  sessions.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

SESSION_COOKIE = "mi_session"
# Internal tool on a trusted network: long enough not to annoy, short enough
# that an unattended laptop is not a standing invitation.
SESSION_IDLE_SECONDS = 8 * 3600
SESSION_ABSOLUTE_SECONDS = 30 * 86400

MIN_PASSWORD_LENGTH = 8

# Failed logins per email before the account is temporarily refused. Counted
# in-process — this is a rate limiter, not a security boundary, and resetting
# it by restarting the API is an acceptable trade for not writing a row on
# every failed attempt.
MAX_FAILED_LOGINS = 10
LOCKOUT_SECONDS = 900
_failed: dict[str, list[float]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problem(password: str) -> Optional[str]:
    """Return a human-readable reason the password is unacceptable, or None.

    Length only. Composition rules push people toward Passw0rd! and a sticky
    note; length is the property that actually costs an attacker something.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def note_failed_login(email: str) -> None:
    import time
    _failed.setdefault(email, []).append(time.time())


def clear_failed_logins(email: str) -> None:
    _failed.pop(email, None)


def is_locked_out(email: str) -> bool:
    import time
    cutoff = time.time() - LOCKOUT_SECONDS
    attempts = [t for t in _failed.get(email, []) if t > cutoff]
    _failed[email] = attempts
    return len(attempts) >= MAX_FAILED_LOGINS


# ----------------------------------------------------------------- sessions


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn, user_id: int, ip: str | None, user_agent: str | None) -> str:
    """Create a session and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn.execute(
        """INSERT INTO sessions
             (token_hash, user_id, created_at, last_seen_at, expires_at, ip, user_agent)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            _hash_token(token),
            user_id,
            now.isoformat(),
            now.isoformat(),
            (now + timedelta(seconds=SESSION_ABSOLUTE_SECONDS)).isoformat(),
            ip,
            (user_agent or "")[:400],
        ),
    )
    return token


def resolve_session(conn, token: str | None) -> Optional[dict[str, Any]]:
    """Return the user behind a session token, or None.

    Enforces both the absolute expiry and the idle timeout, and refreshes
    last_seen_at so an active session keeps rolling.
    """
    if not token:
        return None
    row = conn.execute(
        """SELECT s.id AS session_id, s.last_seen_at, s.expires_at,
                  u.id, u.email, u.full_name, u.role, u.is_active,
                  u.must_change_password, u.is_owner, u.role_template_id
           FROM sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = %s""",
        (_hash_token(token),),
    ).fetchone()
    if not row or not row["is_active"]:
        return None

    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(row["expires_at"]) < now:
        conn.execute("DELETE FROM sessions WHERE id = %s", (row["session_id"],))
        conn.commit()
        return None
    if datetime.fromisoformat(row["last_seen_at"]) + timedelta(
        seconds=SESSION_IDLE_SECONDS
    ) < now:
        conn.execute("DELETE FROM sessions WHERE id = %s", (row["session_id"],))
        conn.commit()
        return None

    conn.execute(
        "UPDATE sessions SET last_seen_at = %s WHERE id = %s",
        (now.isoformat(), row["session_id"]),
    )
    conn.commit()
    return dict(row)


def revoke_session(conn, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash_token(token),))


def revoke_all_sessions(conn, user_id: int) -> None:
    """Used when an account is deactivated, demoted, or has its password
    reset — none of those should leave a live session behind."""
    conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def purge_expired_sessions(conn) -> int:
    """Delete sessions past their absolute expiry.

    resolve_session() already refuses an expired session and deletes that one
    row, but a session nobody returns to is never looked at again and would sit
    in the table forever. Called from the nightly refresh.
    """
    cur = conn.execute("DELETE FROM sessions WHERE expires_at < %s", (now_iso(),))
    return cur.rowcount or 0


# -------------------------------------------------------------- permissions


def effective_permissions(conn, user: dict[str, Any]) -> set[str]:
    """Template permissions, plus per-user grants, minus per-user revokes."""
    if user["role"] == "admin":
        return {
            r["key"] for r in conn.execute("SELECT key FROM permissions")
        }

    perms: set[str] = set()
    if user.get("role_template_id"):
        perms = {
            r["permission_key"]
            for r in conn.execute(
                "SELECT permission_key FROM role_template_permissions WHERE template_id = %s",
                (user["role_template_id"],),
            )
        }
    for r in conn.execute(
        "SELECT permission_key, granted FROM user_permissions WHERE user_id = %s",
        (user["id"],),
    ):
        if r["granted"]:
            perms.add(r["permission_key"])
        else:
            perms.discard(r["permission_key"])
    return perms


# -------------------------------------------------------------------- scope


def get_scopes(conn, user_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT country, city FROM user_scopes WHERE user_id = %s ORDER BY country, city",
            (user_id,),
        )
    ]


def scope_predicate(
    conn, user: dict[str, Any], alias: str = "p"
) -> tuple[str, list[Any]]:
    """SQL fragment restricting a products table to the user's scope.

    Returns ``(sql, params)`` where sql is always a complete boolean
    expression, so callers can splice it in with AND unconditionally without
    worrying about empty strings.

      admin          -> "TRUE"          (unscoped by design)
      no scope rows  -> "FALSE"         (grant required, nothing by default)
      scoped         -> "((country = %s AND city = %s) OR (country = %s) ...)"

    A scope row with city NULL covers every city in that country, including
    ones added to the catalogue later.
    """
    if user["role"] == "admin":
        return "TRUE", []

    scopes = get_scopes(conn, user["id"])
    if not scopes:
        return "FALSE", []

    clauses: list[str] = []
    params: list[Any] = []
    for s in scopes:
        if s["city"] is None:
            clauses.append(f"{alias}.country = %s")
            params.append(s["country"])
        else:
            clauses.append(f"({alias}.country = %s AND {alias}.city = %s)")
            params.extend([s["country"], s["city"]])
    return "(" + " OR ".join(clauses) + ")", params


def product_in_scope(conn, user: dict[str, Any], product_id: int) -> bool:
    """Whether one product is visible to this user.

    Used by the write paths and the by-id reads, where filtering a list is not
    the question — the question is whether to serve this row at all.
    """
    if user["role"] == "admin":
        return True
    sql, params = scope_predicate(conn, user, "p")
    if sql == "FALSE":
        return False
    row = conn.execute(
        f"SELECT 1 FROM products p WHERE p.id = %s AND {sql}",
        [product_id, *params],
    ).fetchone()
    return row is not None


def product_id_for_option(conn, option_id: int) -> Optional[int]:
    """Anchor product for either kind of option.

    Rayna options point at a product directly; competitor options reach it
    through their listing's competitor row.
    """
    row = conn.execute(
        """SELECT COALESCE(o.rayna_product_id, c.rayna_product_id) AS pid
           FROM options o
           LEFT JOIN competitor_listings cl ON cl.id = o.competitor_listing_id
           LEFT JOIN competitors c ON c.id = cl.competitor_id
           WHERE o.id = %s""",
        (option_id,),
    ).fetchone()
    return row["pid"] if row else None


# ---------------------------------------------------------------- audit log


def audit(
    conn,
    actor: Optional[dict[str, Any]],
    action: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    before: Any = None,
    after: Any = None,
    ip: str | None = None,
) -> None:
    """Record one write.

    actor may be None for work done by the nightly cron, which runs without a
    session; those rows are attributed to 'system' so the log never has a gap
    where an actor should be.
    """
    conn.execute(
        """INSERT INTO audit_log
             (actor_user_id, actor_email, action, entity_type, entity_id,
              before_json, after_json, ip, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            (actor or {}).get("id"),
            (actor or {}).get("email") or "system",
            action,
            entity_type,
            None if entity_id is None else str(entity_id),
            json.dumps(before, default=str) if before is not None else None,
            json.dumps(after, default=str) if after is not None else None,
            ip,
            now_iso(),
        ),
    )
