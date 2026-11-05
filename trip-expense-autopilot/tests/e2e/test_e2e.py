from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tea.sources.hanacard_web import HanaCardWeb
from tea.deel_web import DeelWeb, DeelFormError
from tea.ledger import Ledger
from tea.models import AuthRequired, CaptchaRequired, SelectorDrift
from tea.pipeline import run_pipeline
from tea.trip import Trip
from tea.fx import StaticFx

ROOT = Path(__file__).resolve().parents[2]
TRIP_FIXTURE = ROOT / "tests" / "fixtures" / "trip_paris.json"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1200


def load_trip(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for name in ("from_file", "load", "from_dict", "parse"):
        fn = getattr(Trip, name, None)
        if fn is None:
            continue
        try:
            if name in ("from_file", "load"):
                return fn(path)
            return fn(data)
        except Exception:
            continue
    return Trip(**data)


def make_hana(sel_files, tmp_path):
    return HanaCardWeb(
        sel_files["hana"], state_path=tmp_path / "hana_state.json"
    )


def deel_item(txn_id="TXN-0001", category="meal", amount=Decimal("45.00"),
              currency="EUR", policy_status="PASS"):
    return {
        "txn_id": txn_id,
        "category": category,
        "amount": amount,
        "currency": currency,
        "date": "2026-10-13",
        "merchant": "Brasserie Lipp",
        "trip_id": "PAR-2026-10",
        "policy_status": policy_status,
        "policy_reason": "meal cap ok",
    }


def fetch_txns(page, hana):
    return hana.list_transactions(page, date(2026, 8, 1), date(2026, 10, 31))


def test_1_list_transactions(env, sel_files, login, tmp_path):
    hana = make_hana(sel_files, tmp_path)
    login(env)
    txns = fetch_txns(env, hana)
    assert len(txns) == 25
    eur = [t for t in txns if t.currency == "EUR"]
    assert any(t.amount == Decimal("1050.00") for t in eur)
    assert any(t.status == "cancelled" and t.amount < 0 for t in txns)
    assert any(t.status == "partial_cancel" for t in txns)
    assert any(t.currency == "KRW" for t in txns)
    assert all(t.card_last4 == "5678" for t in txns)
    assert all(t.approved_at.tzinfo is not None for t in txns)


@pytest.mark.e2e
def test_2_screenshot_transaction(env, sel_files, login, tmp_path):
    hana = make_hana(sel_files, tmp_path)
    login(env)
    txns = fetch_txns(env, hana)
    txn = txns[20]
    shots = tmp_path / "shots"
    png = hana.screenshot_transaction(env, txn, shots)
    assert png.name == f"{txn.txn_id}.png"
    assert png.is_file()
    assert png.stat().st_size > 1024
    panel = env.locator(".detail-panel")
    assert panel.count() == 0 or not panel.first.is_visible()


@pytest.mark.e2e
def test_3_pipeline(env, sel_files, login, tmp_path):
    hana = make_hana(sel_files, tmp_path)
    login(env)
    txns = fetch_txns(env, hana)
    trip = load_trip(TRIP_FIXTURE)
    fx = StaticFx({
        ("EUR", "KRW"): Decimal("1490"),
        ("USD", "KRW"): Decimal("1330"),
        ("USD", "EUR"): Decimal("0.92"),
    })
    out_dir = tmp_path / "out"
    report = run_pipeline(
        txns,
        trip,
        fx,
        out_dir,
        screenshot=lambda t, d: hana.screenshot_transaction(env, t, d),
    )
    rows = report.rows
    assert rows

    def find(sub):
        return [r for r in rows if sub.lower() in r["merchant"].lower()]

    insurance = [r for r in rows if r["category"] == "insurance"]
    assert insurance, "no insurance txn in fixture data"
    for r in insurance:
        assert r["policy_status"] == "FAIL"

    hotels = find("hotel") or find("호텔")
    assert hotels, "no hotel txn in fixture data"
    assert any(r["policy_status"] == "PASS" for r in hotels)

    lipp = find("lipp")
    assert lipp, "no Brasserie Lipp txn in fixture data"
    assert any(r["policy_status"] == "FLAG" for r in lipp)

    for r in rows:
        assert r["screenshot_url"]
        assert Path(r["screenshot_url"]).is_file()


@pytest.mark.e2e
def test_4_deel_draft(env, sel_files, tmp_path, server):
    ledger = Ledger(tmp_path / "ledger.db")
    deel = DeelWeb(sel_files["deel"], ledger, tmp_path / "deel_out")
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG_BYTES)
    item = deel_item()
    result = deel.prepare_expense(env, item, shot, approve=False)
    assert result == "drafted"
    assert server.deel_submissions == []
    form_png = tmp_path / "deel_out" / f"{item['txn_id']}.deel_form.png"
    assert form_png.is_file()
    assert ledger.get(item["txn_id"]) == "drafted"


@pytest.mark.e2e
def test_5_deel_approve(env, sel_files, tmp_path, server):
    ledger = Ledger(tmp_path / "ledger.db")
    deel = DeelWeb(sel_files["deel"], ledger, tmp_path / "deel_out")
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG_BYTES)
    item = deel_item(txn_id="TXN-APPROVE-1")
    result = deel.prepare_expense(env, item, shot, approve=True)
    assert result == "submitted"
    subs = server.deel_submissions
    assert len(subs) == 1
    assert Decimal(str(subs[0]["amount"])) == Decimal("45.00")
    assert subs[0]["currency"] == "EUR"
    assert subs[0]["category"] == "Meals"
    assert ledger.get(item["txn_id"]) == "submitted"
    assert ledger.all()[0]["ref"]

    result2 = deel.prepare_expense(env, item, shot, approve=True)
    assert result2 == "skipped-duplicate"
    assert len(server.deel_submissions) == 1


@pytest.mark.e2e
def test_6_deel_fail_never_submitted(env, sel_files, tmp_path, server):
    ledger = Ledger(tmp_path / "ledger.db")
    deel = DeelWeb(sel_files["deel"], ledger, tmp_path / "deel_out")
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG_BYTES)
    item = deel_item(txn_id="TXN-FAIL-1", policy_status="FAIL")
    result = deel.prepare_expense(env, item, shot, approve=True)
    assert result == "skipped-fail"
    assert server.deel_submissions == []
    assert ledger.get(item["txn_id"]) == "skipped"


@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_7_hana_session_expired(env, sel_files, tmp_path, server):
    server.set_flag("hana_session_expired")
    hana = make_hana(sel_files, tmp_path)
    with pytest.raises(AuthRequired):
        fetch_txns(env, hana)


@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_8_hana_captcha(env, sel_files, tmp_path, server):
    server.set_flag("hana_captcha")
    hana = make_hana(sel_files, tmp_path)
    with pytest.raises(CaptchaRequired):
        fetch_txns(env, hana)


@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_9_hana_selector_drift(env, sel_files, tmp_path, server, login):
    login(env)
    server.set_flag("hana_selector_drift")
    hana = make_hana(sel_files, tmp_path)
    with pytest.raises(SelectorDrift):
        fetch_txns(env, hana)


@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_10_hana_empty(env, sel_files, tmp_path, server, login):
    login(env)
    server.set_flag("hana_empty")
    hana = make_hana(sel_files, tmp_path)
    txns = fetch_txns(env, hana)
    assert txns == []


@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_11_deel_session_expired(env, sel_files, tmp_path, server):
    server.set_flag("deel_session_expired")
    ledger = Ledger(tmp_path / "ledger.db")
    deel = DeelWeb(sel_files["deel"], ledger, tmp_path / "deel_out")
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG_BYTES)
    item = deel_item(txn_id="TXN-SESS-1")
    with pytest.raises(AuthRequired):
        deel.prepare_expense(env, item, shot, approve=False)
    assert server.deel_submissions == []
    assert ledger.get(item["txn_id"]) is None


@pytest.mark.e2e
@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_12_deel_form_error(env, sel_files, tmp_path, server):
    server.set_flag("deel_form_error")
    ledger = Ledger(tmp_path / "ledger.db")
    deel = DeelWeb(sel_files["deel"], ledger, tmp_path / "deel_out")
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG_BYTES)
    item = deel_item(txn_id="TXN-ERR-1")
    with pytest.raises(DeelFormError):
        deel.prepare_expense(env, item, shot, approve=True)
    assert ledger.get(item["txn_id"]) != "submitted"
    assert server.deel_submissions == []


@pytest.mark.e2e
@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_13_deel_slow(env, sel_files, tmp_path, server):
    server.set_flag("deel_slow")
    ledger = Ledger(tmp_path / "ledger.db")
    deel = DeelWeb(sel_files["deel"], ledger, tmp_path / "deel_out")
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG_BYTES)
    item = deel_item(txn_id="TXN-SLOW-1")
    result = deel.prepare_expense(env, item, shot, approve=True)
    assert result == "submitted"
    assert len(server.deel_submissions) == 1
    assert ledger.get(item["txn_id"]) == "submitted"


@pytest.mark.parametrize("env", [("chromium", "Desktop Chrome")],
                         ids=["chromium-desktop"], indirect=True)
def test_14_not_logged_in(env, sel_files, tmp_path):
    hana = make_hana(sel_files, tmp_path)
    with pytest.raises(AuthRequired):
        fetch_txns(env, hana)


@pytest.mark.e2e
@pytest.mark.parametrize("env", [("webkit", "iPhone 15")],
                         ids=["webkit-iphone15"], indirect=True)
def test_15_mobile_viewport(env, sel_files, login, server):
    login(env)
    env.goto(f"{server.base_url}/hana/history.html")
    env.wait_for_load_state("networkidle")
    scroll_ok = env.evaluate(
        "() => {"
        " const de = document.documentElement;"
        " const wrap = document.querySelector('.table-wrap');"
        " return de.scrollWidth <= window.innerWidth + 1"
        "  || (wrap && getComputedStyle(wrap).overflowX === 'auto');"
        "}"
    )
    assert scroll_ok
    button = env.locator("button:has-text('조회')")
    assert button.count() > 0
    assert button.first.is_visible()
    button.first.click()
