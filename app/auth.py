"""Sign in with Microsoft (OIDC auth code flow), limited to ALLOWED_USER_EMAIL."""
import base64
import json
import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from .config import Config

bp = Blueprint("auth", __name__)
SCOPES = "openid profile email"


def _authority():
    return f"https://login.microsoftonline.com/{Config.MS_TENANT_ID}/oauth2/v2.0"


def _redirect_uri():
    return Config.PUBLIC_BASE_URL.rstrip("/") + "/auth/callback"


def _decode_claims(id_token):
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@bp.route("/login")
def login():
    return render_template("login.html", error=request.args.get("error"))


@bp.route("/auth/start")
def start():
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    session["oauth_state"], session["oauth_nonce"] = state, nonce
    params = {"client_id": Config.MS_CLIENT_ID, "response_type": "code", "redirect_uri": _redirect_uri(),
              "response_mode": "query", "scope": SCOPES, "state": state, "nonce": nonce,
              "prompt": "select_account"}
    return redirect(f"{_authority()}/authorize?{urlencode(params)}")


@bp.route("/auth/callback")
def callback():
    if request.args.get("state") != session.pop("oauth_state", None):
        abort(400)
    if "error" in request.args:
        return redirect(url_for("auth.login", error="Microsoft sign-in was cancelled or failed."))
    r = requests.post(f"{_authority()}/token", timeout=30, data={
        "client_id": Config.MS_CLIENT_ID, "client_secret": Config.MS_CLIENT_SECRET,
        "grant_type": "authorization_code", "code": request.args.get("code", ""),
        "redirect_uri": _redirect_uri(), "scope": SCOPES})
    if r.status_code != 200:
        return redirect(url_for("auth.login", error="Sign-in couldn't be completed. Try again."))
    claims = _decode_claims(r.json()["id_token"])  # received directly from Microsoft over TLS
    email = (claims.get("preferred_username") or claims.get("email") or "").lower()
    if (claims.get("nonce") != session.pop("oauth_nonce", None)
            or claims.get("tid") != Config.MS_TENANT_ID
            or not Config.ALLOWED_USER_EMAIL or email != Config.ALLOWED_USER_EMAIL):
        return redirect(url_for("auth.login", error=f"{email or 'That account'} doesn't have access to this site."))
    session.clear()
    session["user"] = {"email": email, "name": claims.get("name") or email}
    session.permanent = True
    return redirect(url_for("main.appointments"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def require_login(app):
    open_endpoints = {"auth.login", "auth.start", "auth.callback", "static", "main.healthz"}

    @app.before_request
    def _guard():
        if request.endpoint in open_endpoints:
            return None
        if Config.DEMO_MODE and "user" not in session:
            session["user"] = {"email": "demo@example.com", "name": "Cody"}
        if "user" not in session:
            return redirect(url_for("auth.login"))
        if request.method == "POST":
            token = request.form.get("csrf") or request.headers.get("X-CSRF")
            if not token or token != session.get("csrf"):
                abort(400)
        return None

    @app.context_processor
    def _csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return {"csrf": session["csrf"], "user": session.get("user")}
