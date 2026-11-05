from __future__ import annotations

import json
import sys
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent
TESTS_DIR = E2E_DIR.parent
ROOT = TESTS_DIR.parent

for _p in (str(ROOT), str(TESTS_DIR / "mock_sites")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from playwright.sync_api import sync_playwright

from server import MockServer

ENVIRONMENTS = [
    ("chromium", "Desktop Chrome"),
    ("firefox", "Desktop Firefox"),
    ("webkit", "Desktop Safari"),
    ("chromium", "Pixel 7"),
    ("webkit", "iPhone 15"),
    ("chromium", "Galaxy S9+"),
]
ENV_IDS = [f"{b}-{d.replace(' ', '').lower()}" for b, d in ENVIRONMENTS]


@pytest.fixture(scope="session")
def server():
    s = MockServer()
    s.start()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _reset_server(server):
    server.reset()
    yield


@pytest.fixture(scope="session")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def _browsers(pw):
    cache: dict = {}
    yield cache
    for b in cache.values():
        try:
            b.close()
        except Exception:
            pass


@pytest.fixture(params=ENVIRONMENTS, ids=ENV_IDS)
def env(request, pw, _browsers):
    browser_type, device_name = request.param
    browser = _browsers.get(browser_type)
    if browser is None:
        browser = getattr(pw, browser_type).launch()
        _browsers[browser_type] = browser
    device = dict(pw.devices[device_name])
    if browser_type == "firefox":
        device.pop("is_mobile", None)
    context = browser.new_context(
        locale="ko-KR", timezone_id="Asia/Seoul", **device
    )
    page = context.new_page()
    page.set_default_timeout(15000)
    yield page
    context.close()


@pytest.fixture
def sel_files(tmp_path, server):
    base = server.base_url
    hana = json.loads(
        (ROOT / "selectors" / "hanacard.json").read_text(encoding="utf-8")
    )
    hana["login_url"] = f"{base}/hana/login.html"
    hana["history_url"] = f"{base}/hana/history.html"
    hana_path = tmp_path / "hanacard.json"
    hana_path.write_text(json.dumps(hana), encoding="utf-8")

    deel = json.loads(
        (ROOT / "selectors" / "deel.json").read_text(encoding="utf-8")
    )
    deel["expenses_url"] = f"{base}/deel/expenses.html"
    deel_path = tmp_path / "deel.json"
    deel_path.write_text(json.dumps(deel), encoding="utf-8")

    return {"hana": hana_path, "deel": deel_path}


@pytest.fixture
def login(server):
    def _login(page):
        page.goto(f"{server.base_url}/hana/login.html")
        page.fill("#id", "tester")
        page.fill("#password", "s3cret-value")
        page.click("button[type=submit]")
        page.wait_for_function(
            "() => { const e = document.getElementById('logged-in'); return e && getComputedStyle(e).display !== 'none'; }"
        )

    return _login
