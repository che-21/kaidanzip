"""GitHub OAuth 로그인 (웹 화면용).

GitHub는 OIDC를 제공하지 않아 Streamlit 내장 st.login 대신 OAuth 웹 흐름을 직접 구현한다.

흐름
  1. authorize_url(): github.com/login/oauth/authorize 로 보낸다. state = 서명된 nonce(서버 저장 불필요).
  2. GitHub가 redirect_uri?code=…&state=… 로 돌려보낸다.
  3. verify_state() → exchange_code() → fetch_user() → is_allowed().

설정 (.env)
  GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET   GitHub OAuth App 값 (둘 다 있으면 로그인 켜짐)
  MD2SHORT_ALLOWED_GITHUB_USERS            쉼표로 구분한 허용 GitHub ID. 비어 있으면 아무도 못 들어옴
  MD2SHORT_PUBLIC_URL                      OAuth App의 callback URL (기본 http://localhost:8501)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
SCOPE = "read:user"
STATE_MAX_AGE_S = 600


class AuthError(Exception):
    """사용자에게 보여 줄 한국어 메시지를 담는다."""


@dataclass
class AuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    allowed: set[str]

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)


def load_config() -> AuthConfig:
    allowed = {u.strip().lower() for u in os.environ.get("MD2SHORT_ALLOWED_GITHUB_USERS", "").split(",") if u.strip()}
    return AuthConfig(
        client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
        client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
        redirect_uri=os.environ.get("MD2SHORT_PUBLIC_URL", "http://localhost:8501").rstrip("/"),
        allowed=allowed,
    )


# ---------- state (CSRF 방지, 서버 저장 없이 HMAC 서명) ----------

def _sign(secret: str, payload: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def make_state(secret: str, now: float | None = None) -> str:
    payload = f"{int(now if now is not None else time.time())}.{secrets.token_urlsafe(12)}"
    return f"{payload}.{_sign(secret, payload)}"


def verify_state(state: str, secret: str, now: float | None = None, max_age: int = STATE_MAX_AGE_S) -> None:
    try:
        ts, nonce, sig = state.split(".")
        issued = int(ts)
    except (ValueError, AttributeError):
        raise AuthError("로그인 요청이 올바르지 않습니다. 다시 로그인해 주세요.")
    if not hmac.compare_digest(sig, _sign(secret, f"{ts}.{nonce}")):
        raise AuthError("로그인 요청 서명이 맞지 않습니다. 다시 로그인해 주세요.")
    if (now if now is not None else time.time()) - issued > max_age:
        raise AuthError("로그인 요청 시간이 지났습니다. 다시 로그인해 주세요.")


# ---------- OAuth ----------

def authorize_url(cfg: AuthConfig, state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": SCOPE,
        "state": state,
        "allow_signup": "false",
    })


def exchange_code(cfg: AuthConfig, code: str) -> str:
    try:
        resp = httpx.post(TOKEN_URL, headers={"Accept": "application/json"}, timeout=20, data={
            "client_id": cfg.client_id, "client_secret": cfg.client_secret,
            "code": code, "redirect_uri": cfg.redirect_uri,
        })
    except httpx.HTTPError as exc:
        raise AuthError(f"GitHub에 연결하지 못했습니다: {exc}") from exc
    data = resp.json() if resp.status_code < 500 else {}
    token = data.get("access_token")
    if not token:
        reason = data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}"
        raise AuthError(f"GitHub 로그인에 실패했습니다: {reason}")
    return token


def fetch_user(token: str) -> dict:
    try:
        resp = httpx.get(USER_URL, timeout=20, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    except httpx.HTTPError as exc:
        raise AuthError(f"GitHub 사용자 정보를 가져오지 못했습니다: {exc}") from exc
    if resp.status_code != 200:
        raise AuthError(f"GitHub 사용자 정보를 가져오지 못했습니다(HTTP {resp.status_code}).")
    u = resp.json()
    return {"login": u["login"], "id": u["id"], "name": u.get("name") or u["login"], "avatar_url": u.get("avatar_url")}


def is_allowed(cfg: AuthConfig, login: str) -> bool:
    return login.lower() in cfg.allowed


def complete_login(cfg: AuthConfig, code: str, state: str) -> dict:
    """콜백 처리: state 검증 → 토큰 교환 → 사용자 조회 → 허용 목록 확인. 토큰은 저장하지 않는다."""
    verify_state(state, cfg.client_secret)
    user = fetch_user(exchange_code(cfg, code))
    if not is_allowed(cfg, user["login"]):
        raise AuthError(
            f"'{user['login']}' 계정은 이 MD2Short를 쓸 수 없습니다. 관리자에게 .env의 "
            "MD2SHORT_ALLOWED_GITHUB_USERS에 추가해 달라고 요청하세요.")
    return user
