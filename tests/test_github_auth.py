import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from md2short import github_auth as ga
from md2short.state import JobState

from .conftest import ROOT

APP = str(ROOT / "webapp" / "app.py")
CFG = ga.AuthConfig(client_id="cid", client_secret="sec", redirect_uri="http://localhost:8501", allowed={"octo-user"})


def test_state_roundtrip_and_tamper_and_expiry():
    s = ga.make_state("sec", now=1000)
    ga.verify_state(s, "sec", now=1100)
    with pytest.raises(ga.AuthError):
        ga.verify_state(s, "other-secret", now=1100)
    with pytest.raises(ga.AuthError):
        ga.verify_state(s.replace(s.split(".")[1], "forged"), "sec", now=1100)
    with pytest.raises(ga.AuthError):
        ga.verify_state(s, "sec", now=1000 + ga.STATE_MAX_AGE_S + 1)
    with pytest.raises(ga.AuthError):
        ga.verify_state("garbage", "sec")


def test_authorize_url_params():
    q = parse_qs(urlparse(ga.authorize_url(CFG, "st")).query)
    assert q["client_id"] == ["cid"] and q["redirect_uri"] == ["http://localhost:8501"]
    assert q["scope"] == ["read:user"] and q["state"] == ["st"]


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _mock_github(monkeypatch, login="octo-user", token_body=None):
    calls = {}

    def post(url, headers=None, timeout=None, data=None):
        calls["post"] = (url, data)
        return _Resp(200, token_body if token_body is not None else {"access_token": "gho_x"})

    def get(url, timeout=None, headers=None):
        calls["get"] = (url, headers)
        return _Resp(200, {"login": login, "id": 7, "name": "Tester", "avatar_url": None})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    return calls


def test_complete_login_allowed(monkeypatch):
    calls = _mock_github(monkeypatch)
    user = ga.complete_login(CFG, "code123", ga.make_state("sec"))
    assert user["login"] == "octo-user"
    assert calls["post"][1]["code"] == "code123"
    assert calls["get"][1]["Authorization"] == "Bearer gho_x"


def test_complete_login_not_allowed_and_case_insensitive(monkeypatch):
    _mock_github(monkeypatch, login="stranger")
    with pytest.raises(ga.AuthError) as exc:
        ga.complete_login(CFG, "c", ga.make_state("sec"))
    assert "stranger" in str(exc.value)
    _mock_github(monkeypatch, login="OCTO-USER")
    assert ga.complete_login(CFG, "c", ga.make_state("sec"))["login"] == "OCTO-USER"


def test_complete_login_bad_code(monkeypatch):
    _mock_github(monkeypatch, token_body={"error": "bad_verification_code", "error_description": "The code passed is incorrect"})
    with pytest.raises(ga.AuthError) as exc:
        ga.complete_login(CFG, "c", ga.make_state("sec"))
    assert "incorrect" in str(exc.value)


def test_complete_login_rejects_bad_state_before_network(monkeypatch):
    calls = _mock_github(monkeypatch)
    with pytest.raises(ga.AuthError):
        ga.complete_login(CFG, "c", "1.x.y")
    assert calls == {}


def test_empty_allowlist_denies_everyone(monkeypatch):
    monkeypatch.delenv("MD2SHORT_ALLOWED_GITHUB_USERS", raising=False)
    cfg = ga.load_config()
    assert not ga.is_allowed(cfg, "octo-user")


# ---------------- 웹 화면 ----------------

@pytest.fixture
def auth_env(isolated, monkeypatch):
    monkeypatch.setenv("MD2SHORT_FAKE_IMAGES", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MD2SHORT_ALLOWED_GITHUB_USERS", "octo-user")
    return isolated


def test_app_requires_login(auth_env):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "github.com/login/oauth/authorize" in html and "client_id=cid" in html
    assert not at.button  # 업로드·작업 버튼 없음


def test_app_callback_logs_in_and_filters_jobs(auth_env, monkeypatch):
    _mock_github(monkeypatch)
    jobs = auth_env / "jobs"
    mine = JobState.create(jobs / "sf_20261126_aaaaaa", "sf_20261126_aaaaaa", {"owner": "octo-user"})
    JobState.create(jobs / "sf_20261126_bbbbbb", "sf_20261126_bbbbbb", {"owner": "someone"})
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["code"] = "abc"
    at.query_params["state"] = ga.make_state("sec")
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["user"]["login"] == "octo-user"
    labels = [b.label for b in at.sidebar.button]
    assert "로그아웃" in labels
    assert any(l.startswith("sf_20261126_aaaaaa") for l in labels)
    assert not any(l.startswith("sf_20261126_bbbbbb") for l in labels)
    assert mine.status == "created"


def test_app_callback_denied_user(auth_env, monkeypatch):
    _mock_github(monkeypatch, login="stranger")
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["code"] = "abc"
    at.query_params["state"] = ga.make_state("sec")
    at.run()
    assert "user" not in at.session_state or not at.session_state["user"]
    assert any("stranger" in e.value for e in at.error)


def test_app_without_github_config_runs_open(isolated, monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("로그인 꺼짐" in c.value for c in at.sidebar.caption)
