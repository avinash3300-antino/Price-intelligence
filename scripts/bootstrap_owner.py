"""Create the owner account and attribute pre-RBAC work to it.

Run once per environment, after migrations 002 and 003.

The owner is the account that cannot be demoted, deactivated or deleted — the
guarantee that the system can never be locked out of itself. Everything else,
including other admins, is created through the app.

Existing mappings, competitors and listings predate RBAC and have no author.
They are backfilled to the owner rather than left NULL so that "who made this
link?" always has an answer, and the audit log records the backfill itself so
the attribution is not mistaken for real authorship later.

Usage:
    python -m scripts.bootstrap_owner --email you@raynatours.com --name "Your Name"
    python -m scripts.bootstrap_owner --email ... --password 'chosen-password'

Without --password a strong one is generated and printed once. It is stored
only as an argon2 hash, so if the printed value is lost the fix is to re-run
with --reset-password rather than to read it back out.
"""
from __future__ import annotations

import argparse
import secrets
import sys

from src import auth, db


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", default="Owner")
    ap.add_argument("--password", default=None,
                    help="omit to generate one and print it")
    ap.add_argument("--reset-password", action="store_true",
                    help="owner already exists: set a new password and end their sessions")
    args = ap.parse_args()

    email = args.email.strip().lower()
    password = args.password or secrets.token_urlsafe(12)
    problem = auth.password_problem(password)
    if problem:
        print(f"FATAL: {problem}", file=sys.stderr)
        return 2

    conn = db.get_conn()
    try:
        existing = conn.execute(
            "SELECT id, email, is_owner FROM users WHERE email = %s", (email,)
        ).fetchone()
        owner = conn.execute(
            "SELECT id, email FROM users WHERE is_owner"
        ).fetchone()

        if owner and (not existing or existing["id"] != owner["id"]):
            print(f"FATAL: an owner already exists ({owner['email']}). "
                  f"Only one owner is permitted; create further admins in the app.",
                  file=sys.stderr)
            return 2

        admin_template = conn.execute(
            "SELECT id FROM role_templates WHERE name = 'Admin'"
        ).fetchone()

        if existing:
            if not args.reset_password:
                print(f"Owner {email} already exists (id={existing['id']}). "
                      f"Pass --reset-password to set a new one.")
                return 0
            conn.execute(
                """UPDATE users
                   SET password_hash = %s, must_change_password = TRUE,
                       is_active = TRUE
                   WHERE id = %s""",
                (auth.hash_password(password), existing["id"]),
            )
            auth.revoke_all_sessions(conn, existing["id"])
            user_id = existing["id"]
            action = "owner.password_reset"
        else:
            row = conn.execute(
                """INSERT INTO users
                     (email, password_hash, full_name, role, is_active,
                      must_change_password, is_owner, role_template_id, created_at)
                   VALUES (%s, %s, %s, 'admin', TRUE, TRUE, TRUE, %s, %s)
                   RETURNING id""",
                (
                    email,
                    auth.hash_password(password),
                    args.name,
                    admin_template["id"] if admin_template else None,
                    auth.now_iso(),
                ),
            ).fetchone()
            user_id = row["id"]
            action = "owner.created"

        # Attribute pre-RBAC work. Only rows with no author are touched, so
        # re-running never rewrites real attribution.
        backfilled = {}
        for table in ("mappings", "competitors", "competitor_listings"):
            cur = conn.execute(
                f"UPDATE {table} SET created_by = %s WHERE created_by IS NULL",
                (user_id,),
            )
            backfilled[table] = cur.rowcount or 0

        actor = {"id": user_id, "email": email}
        auth.audit(conn, actor, action, "user", user_id,
                   after={"email": email, "role": "admin", "is_owner": True})
        if any(backfilled.values()):
            auth.audit(
                conn, actor, "attribution.backfill", "database", None,
                after={
                    "assigned_to": email,
                    "rows": backfilled,
                    "note": "rows created before RBAC existed; authorship inferred, not recorded",
                },
            )
        conn.commit()
    finally:
        conn.close()

    print("=" * 62)
    print(f"  owner   : {email}  (id={user_id})")
    if args.password:
        print("  password: (as supplied)")
    else:
        print(f"  password: {password}")
        print("  ^ shown once. Store it now; it is kept only as a hash.")
    print("  The owner must change this password at first login.")
    print()
    print("  backfilled created_by:")
    for t, n in backfilled.items():
        print(f"    {t:<22} {n:>6} rows")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
