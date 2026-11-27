import hashlib
import os
import secrets
import time
from html import escape

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import connect

router = APIRouter(prefix="/admin", include_in_schema=False)
password_hasher = PasswordHasher()
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() != "false"
COOKIE_NAME = "__Host-wishlist_session" if COOKIE_SECURE else "wishlist_session"
SESSION_SECONDS = 8 * 60 * 60
MAX_FAILURES = 5
FAILURE_WINDOW = 1 * 60

LOGIN_FORM = """<!doctype html>
<html lang="de"><meta charset="utf-8"><title>Wishlist Admin Login</title>
<h1>Wishlist Admin</h1>
<form method="post" action="/admin/login">
<label>Passwort <input type="password" name="password" required autocomplete="current-password"></label>
<button type="submit">Einloggen</button>
</form></html>"""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_session(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    db = connect()
    try:
        return db.execute(
            "SELECT csrf_token FROM admin_sessions WHERE token_hash = ? AND expires_at > ?",
            (token_hash(token), int(time.time())),
        ).fetchone()
    finally:
        db.close()


def require_admin(request: Request):
    session = get_session(request)
    if session is None:
        raise HTTPException(401, "Not authenticated")
    return session


def require_csrf(session, csrf_token: str):
    if not secrets.compare_digest(session["csrf_token"], csrf_token):
        raise HTTPException(403, "Invalid CSRF token")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_session(request):
        return RedirectResponse("/admin", status_code=303)
    return HTMLResponse(LOGIN_FORM, headers={"Cache-Control": "no-store"})


@router.post("/login")
def login(request: Request, password: str = Form(max_length=1024)):
    saved_hash = os.getenv("ADMIN_PASSWORD_HASH")
    if not saved_hash:
        raise HTTPException(503, "Admin password not configured")

    ip = request.client.host if request.client else "unknown"
    now = int(time.time())
    db = connect()
    try:
        row = db.execute(
            "SELECT failures, last_failure FROM login_attempts WHERE ip = ?", (ip,)
        ).fetchone()
        if row and row["failures"] >= MAX_FAILURES and now - row["last_failure"] < FAILURE_WINDOW:
            raise HTTPException(429, "Too many login attempts")

        try:
            valid = password_hasher.verify(saved_hash, password)
        except (InvalidHashError, VerificationError):
            valid = False

        if not valid:
            db.execute("""
                INSERT INTO login_attempts (ip, failures, last_failure) VALUES (?, 1, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    failures = CASE
                        WHEN excluded.last_failure - login_attempts.last_failure >= ? THEN 1
                        ELSE login_attempts.failures + 1
                    END,
                    last_failure = excluded.last_failure
            """, (ip, now, FAILURE_WINDOW))
            db.commit()
            return HTMLResponse(
                "<p>Falsches Passwort.</p>" + LOGIN_FORM,
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
        db.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now,))
        db.execute(
            "INSERT INTO admin_sessions (token_hash, csrf_token, expires_at) VALUES (?, ?, ?)",
            (token_hash(token), csrf_token, now + SESSION_SECONDS),
        )
        db.commit()
    finally:
        db.close()

    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_SECONDS, secure=COOKIE_SECURE,
        httponly=True, samesite="strict", path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("", response_class=HTMLResponse)
def admin_page(request: Request):
    session = get_session(request)
    if session is None:
        return RedirectResponse("/admin/login", status_code=303)
    csrf = escape(session["csrf_token"], quote=True)
    return HTMLResponse(f"""<!doctype html>
<html lang="de"><meta charset="utf-8"><title>Wishlist Admin</title>
<h1>Wishlist Admin</h1><p>Du bist eingeloggt.</p>
<form method="post" action="/admin/logout">
<input type="hidden" name="csrf_token" value="{csrf}">
<button type="submit">Ausloggen</button>
</form></html>""", headers={"Cache-Control": "no-store"})


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form()):
    session = require_admin(request)
    require_csrf(session, csrf_token)
    token = request.cookies[COOKIE_NAME]
    db = connect()
    try:
        db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash(token),))
        db.commit()
    finally:
        db.close()

    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response
