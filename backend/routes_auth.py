"""Sign-in, sign-out, session identity and password change."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.deps import client_ip, conn, get_current_user
from src import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=auth.MIN_PASSWORD_LENGTH)


class ScopeOut(BaseModel):
    country: str
    city: Optional[str] = None


class MeResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_owner: bool
    must_change_password: bool
    permissions: list[str]
    scopes: list[ScopeOut]


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_ABSOLUTE_SECONDS,
        httponly=True,      # not readable from JS, so XSS cannot lift it
        samesite="lax",     # survives normal navigation, blocks cross-site POSTs
        # secure=True is deliberately not set: this deployment is HTTP on an
        # internal network. Set it the day the app gets TLS, or the cookie
        # stops being sent at all.
        path="/",
    )


@router.post("/login", response_model=MeResponse)
def login(req: LoginRequest, request: Request, response: Response):
    email = req.email.strip().lower()

    if auth.is_locked_out(email):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again in 15 minutes.",
        )

    with conn() as c:
        row = c.execute(
            """SELECT id, email, password_hash, full_name, role, is_active,
                      must_change_password, is_owner, role_template_id
               FROM users WHERE email = %s""",
            (email,),
        ).fetchone()

        # Identical response whether the account is missing, inactive or the
        # password is wrong — otherwise this endpoint enumerates who has an
        # account here.
        if (
            not row
            or not row["is_active"]
            or not auth.verify_password(row["password_hash"], req.password)
        ):
            auth.note_failed_login(email)
            auth.audit(c, None, "auth.login_failed", "user", email, ip=client_ip(request))
            c.commit()
            raise HTTPException(status_code=401, detail="Invalid email or password")

        auth.clear_failed_logins(email)
        token = auth.create_session(
            c, row["id"], client_ip(request), request.headers.get("user-agent")
        )
        c.execute(
            "UPDATE users SET last_login_at = %s WHERE id = %s",
            (auth.now_iso(), row["id"]),
        )
        user = dict(row)
        auth.audit(c, user, "auth.login", "user", row["id"], ip=client_ip(request))
        perms = sorted(auth.effective_permissions(c, user))
        scopes = auth.get_scopes(c, row["id"])
        c.commit()

    _set_session_cookie(response, token)
    return MeResponse(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        role=user["role"],
        is_owner=user["is_owner"],
        must_change_password=user["must_change_password"],
        permissions=perms,
        scopes=[ScopeOut(**s) for s in scopes],
    )


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.SESSION_COOKIE)
    with conn() as c:
        user = auth.resolve_session(c, token)
        auth.revoke_session(c, token)
        if user:
            auth.audit(c, user, "auth.logout", "user", user["id"], ip=client_ip(request))
        c.commit()
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
def me(user: dict[str, Any] = Depends(get_current_user)):
    return MeResponse(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        role=user["role"],
        is_owner=user["is_owner"],
        must_change_password=user["must_change_password"],
        permissions=user["permissions"],
        scopes=[ScopeOut(**s) for s in user["scopes"]],
    )


@router.post("/change-password", status_code=204)
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    problem = auth.password_problem(req.new_password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if req.new_password == req.current_password:
        raise HTTPException(
            status_code=400, detail="New password must differ from the current one."
        )

    with conn() as c:
        row = c.execute(
            "SELECT password_hash FROM users WHERE id = %s", (user["id"],)
        ).fetchone()
        if not row or not auth.verify_password(row["password_hash"], req.current_password):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        c.execute(
            """UPDATE users
               SET password_hash = %s, must_change_password = FALSE
               WHERE id = %s""",
            (auth.hash_password(req.new_password), user["id"]),
        )
        # The password just changed; every other session for this account is
        # now suspect. The current one is re-issued below so the user is not
        # bounced to the login screen for doing the right thing.
        auth.revoke_all_sessions(c, user["id"])
        auth.audit(c, user, "auth.password_changed", "user", user["id"],
                   ip=client_ip(request))
        token = auth.create_session(
            c, user["id"], client_ip(request), request.headers.get("user-agent")
        )
        c.commit()

    response = Response(status_code=204)
    _set_session_cookie(response, token)
    return response
