import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import ConfigError, create_app

GOOD = dict(
    app_password="correct-horse-battery",
    session_secret="s" * 48,
    public_base_url="https://hm.example.test",
)


def make(tmp_path, google, **over):
    kw = dict(GOOD, master_key=Fernet.generate_key().decode(), http_client=google.client(), production=True)
    kw.update(over)
    return create_app(database_url=f"sqlite:///{tmp_path}/prod.db", **kw)


@pytest.mark.parametrize(
    "over,needle",
    [
        ({"app_password": ""}, "HM_APP_PASSWORD"),
        ({"app_password": "short"}, "HM_APP_PASSWORD"),
        ({"session_secret": "x"}, "HM_SESSION_SECRET"),
        ({"public_base_url": "http://hm.example.test"}, "HM_PUBLIC_BASE_URL"),
        ({"master_key": ""}, "HM_MASTER_KEY"),
    ],
)
def test_production_refuses_unsafe_config(tmp_path, google, monkeypatch, over, needle):
    for k in ("HM_APP_PASSWORD", "HM_SESSION_SECRET", "HM_PUBLIC_BASE_URL", "HM_MASTER_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError, match=needle):
        make(tmp_path, google, **over)


@pytest.fixture
def prod(tmp_path, google):
    app = make(tmp_path, google)
    with TestClient(app, base_url="https://hm.example.test", follow_redirects=False) as c:
        yield c


def login(c):
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    r = c.post("/login", data={"csrf": tok, "password": GOOD["app_password"]})
    assert r.headers["location"] == "/"
    return tok


@pytest.mark.parametrize(
    "path",
    ["/", "/complexes", "/complexes/1", "/import", "/review", "/settings", "/records/1", "/import/manual"],
)
def test_unauthenticated_pages_redirect(prod, path):
    r = prod.get(path)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_unauthenticated_api_and_writes_rejected(prod):
    assert prod.get("/api/complexes/1/series").status_code == 401
    for path in ("/sheet/sync", "/import/confirm", "/settings/secrets", "/oauth/google/start", "/complexes/1/remove"):
        r = prod.post(path, data={"csrf": "x"})
        assert r.status_code in (303, 400), path
        assert r.headers.get("location") in (None, "/login")


def test_login_page_leaks_nothing(prod):
    html = prod.get("/login").text
    for word in ("래미안", "검토 대기", "설정", "Google", "/settings"):
        assert word not in html


def test_cookie_is_secure_httponly_lax(prod):
    prod.get("/login")
    r = prod.get("/login")
    login(prod)
    tok = re.search(r'name="csrf" value="([^"]+)"', prod.get("/import").text).group(1)
    r = prod.post("/logout", data={"csrf": tok})
    raw = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    assert raw and all("secure" in v.lower() and "httponly" in v.lower() and "samesite=lax" in v.lower() for v in raw)


def test_security_headers(prod):
    r = prod.get("/login")
    h = r.headers
    assert h["strict-transport-security"].startswith("max-age=")
    assert h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"


def test_owner_login_then_access(prod):
    login(prod)
    assert prod.get("/").status_code == 200
    assert prod.get("/settings").status_code == 200


def test_login_rate_limited(prod):
    tok = re.search(r'name="csrf" value="([^"]+)"', prod.get("/login").text).group(1)
    for _ in range(10):
        prod.post("/login", data={"csrf": tok, "password": "wrong-password-xx"})
    r = prod.post("/login", data={"csrf": tok, "password": GOOD["app_password"]})
    assert r.headers["location"] == "/login"
    assert prod.get("/").status_code == 303


def test_oauth_redirect_uri_uses_public_base(prod):
    tok = login(prod)
    tok = re.search(r'name="csrf" value="([^"]+)"', prod.get("/settings").text).group(1)
    prod.post("/settings/secrets", data={"csrf": tok, "name": "google_client_id", "value": "cid"})
    prod.post("/settings/secrets", data={"csrf": tok, "name": "google_client_secret", "value": "sec"})
    r = prod.post("/oauth/google/start", data={"csrf": tok})
    assert "redirect_uri=https%3A%2F%2Fhm.example.test%2Foauth%2Fgoogle%2Fcallback" in r.headers["location"]


def test_csrf_enforced_when_logged_in(prod):
    login(prod)
    assert prod.post("/complexes/1/remove", data={"csrf": "forged"}).status_code == 400


def test_backup_and_restore_roundtrip(tmp_path):
    db = tmp_path / "live.db"
    with sqlite3.connect(db) as c:
        c.execute("create table t(x)")
        c.execute("insert into t values (1)")
    env = {"HM_DATABASE_URL": f"sqlite:///{db}", "PATH": "/usr/bin:/bin"}
    script = Path(__file__).resolve().parents[1] / "scripts" / "backup.py"
    out = subprocess.run([sys.executable, str(script), "backup", str(tmp_path / "bk")], env=env, capture_output=True, text=True, check=True)
    bfile = out.stdout.strip()
    with sqlite3.connect(db) as c:
        c.execute("insert into t values (2)")
    subprocess.run([sys.executable, str(script), "restore", bfile], env=env, capture_output=True, text=True, check=True)
    with sqlite3.connect(db) as c:
        assert [r[0] for r in c.execute("select x from t")] == [1]
    assert list(tmp_path.glob("live.pre-restore-*.db"))
