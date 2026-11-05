import threading
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import make_txn
from tea.deel_web import DeelFormError, DeelWeb
from tea.fx import StaticFx
from tea.ledger import Ledger
from tea.pipeline import deel_items, run_pipeline

SELECTORS = Path(__file__).resolve().parent.parent / "selectors" / "deel.json"


class ExplodingPage:
    def __getattr__(self, name):
        raise AssertionError(f"page.{name} must not be called")


def _item(txn_id="T1", status="PASS"):
    return {
        "txn_id": txn_id, "category": "meal", "amount": Decimal("12.00"), "currency": "EUR",
        "date": "2026-10-13", "merchant": "CAFE", "trip_id": "PAR", "policy_status": status, "policy_reason": "",
    }


def test_submitting_is_not_resubmitted_after_crash(tmp_path):
    ledger = Ledger(tmp_path / "l.db")
    ledger.set("T1", "submitting")
    deel = DeelWeb(SELECTORS, ledger, out_dir=tmp_path)
    png = tmp_path / "s.png"
    png.write_bytes(b"x")
    assert deel.prepare_expense(ExplodingPage(), _item(), png, approve=True) == "needs-verification"
    with pytest.raises(ValueError):
        ledger.set("T1", "drafted")
    ledger.resolve_submitting("T1", submitted=True, ref="EXP-9")
    assert ledger.get("T1") == "submitted"


def test_missing_screenshot_skips_without_touching_page(tmp_path):
    deel = DeelWeb(SELECTORS, Ledger(tmp_path / "l.db"), out_dir=tmp_path)
    assert deel.prepare_expense(ExplodingPage(), _item(), tmp_path / "missing.png", approve=True) == "skipped-no-evidence"


def test_fail_item_never_touches_page(tmp_path):
    deel = DeelWeb(SELECTORS, Ledger(tmp_path / "l.db"), out_dir=tmp_path)
    png = tmp_path / "s.png"
    png.write_bytes(b"x")
    assert deel.prepare_expense(ExplodingPage(), _item(status="FAIL"), png, approve=True) == "skipped-fail"


def test_ambiguous_submit_error_is_not_rejected():
    assert DeelFormError("timeout", rejected=False).rejected is False
    assert DeelFormError("Receipt rejected").rejected is True


def test_concurrent_ledger_writers_only_one_submits(tmp_path):
    path = tmp_path / "l.db"
    Ledger(path).set("T1", "drafted")
    wins, errors = [], []

    def worker():
        led = Ledger(path)
        try:
            led.set("T1", "submitting")
            wins.append(1)
        except ValueError:
            errors.append(1)
        finally:
            led.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert len(errors) == 7


def test_outside_trip_flag_is_not_reimbursable(paris_trip, tmp_path):
    t = make_txn("DUTY FREE SHOP", "80", "EUR", "2026-10-02T12:00:00+02:00", country="FR")
    from tea.policy.rules import evaluate

    res = evaluate([t], paris_trip, StaticFx({}), {t.txn_id: "other"})[t.txn_id]
    assert res.status == "FLAG"
    assert res.reimbursable == Decimal("0.00")


def test_deel_items_never_include_fail_even_with_amount(paris_trip, tmp_path):
    t = make_txn("AXA ASSURANCE VOYAGE", "45", "EUR", "2026-10-14T12:00:00+02:00", country="FR")
    report = run_pipeline([t], paris_trip, StaticFx({}), tmp_path)
    assert report.rows[0]["policy_status"] == "FAIL"
    assert deel_items(report.rows) == []
