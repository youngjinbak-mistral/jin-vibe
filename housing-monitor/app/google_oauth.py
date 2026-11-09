import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SCOPES = ("openid", "email", SHEETS_SCOPE)


class OAuthError(RuntimeError):
    pass


class ReconnectRequired(OAuthError):
    pass


@dataclass
class TokenBundle:
    access_token: str
    expires_at: float
    refresh_token: str | None
    email: str | None
    scope: str


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorization_url(client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent select_account",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return AUTH_URL + "?" + urlencode(params)


def _email_from_id_token(id_token: str | None) -> str | None:
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except (IndexError, ValueError):
        return None


def _bundle(data: dict, refresh_token: str | None) -> TokenBundle:
    return TokenBundle(
        access_token=data["access_token"],
        expires_at=time.time() + int(data.get("expires_in", 3600)) - 60,
        refresh_token=data.get("refresh_token") or refresh_token,
        email=_email_from_id_token(data.get("id_token")),
        scope=data.get("scope", ""),
    )


def exchange_code(
    http: httpx.Client, client_id: str, client_secret: str, code: str, redirect_uri: str, code_verifier: str
) -> TokenBundle:
    r = http.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    if r.status_code != 200:
        raise OAuthError(f"Google 토큰 교환 실패 (HTTP {r.status_code})")
    bundle = _bundle(r.json(), None)
    if not bundle.refresh_token:
        raise OAuthError("Google이 갱신 토큰을 발급하지 않았습니다. 다시 연결해 주세요.")
    if SHEETS_SCOPE not in bundle.scope.split():
        raise OAuthError("Google Sheets 권한이 승인되지 않았습니다. 연결 시 Sheets 권한을 허용해 주세요.")
    return bundle


def refresh(http: httpx.Client, client_id: str, client_secret: str, refresh_token: str) -> TokenBundle:
    r = http.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if r.status_code in (400, 401):
        try:
            err = r.json().get("error")
        except ValueError:
            err = None
        if err in ("invalid_grant", "unauthorized_client", "invalid_client"):
            raise ReconnectRequired("Google 연결이 만료되었거나 해제되었습니다. 한 번 다시 연결해 주세요.")
    if r.status_code != 200:
        raise OAuthError(f"Google 토큰 갱신 실패 (HTTP {r.status_code})")
    return _bundle(r.json(), refresh_token)


def fetch_email(http: httpx.Client, access_token: str) -> str | None:
    r = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code != 200:
        return None
    return r.json().get("email")


def revoke(http: httpx.Client, token: str) -> None:
    http.post(REVOKE_URL, data={"token": token})
