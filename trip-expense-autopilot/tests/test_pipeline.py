from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from conftest import make_txn, paris_trip  # noqa: F401
from tea.fx import StaticFx
from tea.models import AuthRequired, Transaction
from tea.pipeline import deel_items, dedupe, run_pipeline, select_trip_txns


@pytest.fixture
def fx():
    return StaticFx({("EUR", "KRW"): Decimal("1490")})


def txn_in_paris(merchant, amount, day, hour=12, **kw):
    return make_txn(merchant, Decimal(amount), "EUR", f"2026-10-{day}T{hour:02d}:00:00+02:00", **kw)


class SheetSink:
    def __init__(self):
        self.calls: list[str] = []
        self.rows: list[dict] = []

    def ensure_header(self):
        self.calls.append("ensure_header")

    def upsert(self, rows):
        self.calls.append("upsert")
        self.rows = list(rows)
        return {"updated": 0, "appended": len(rows)}


def shot_ok(txn, out_dir):
    p = out_dir / f"{txn.txn_id}.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def test_dedupe_collapses_same_txn_id():
    a = txn_in_paris("HOTEL PARIS", "200", 13)
    b = make_txn("HOTEL PARIS", Decimal("200"), "EUR", a.approved_at.isoformat())
    assert a.txn_id == b.txn_id
    out = dedupe([a, b, a])
    assert len(out) == 1


def test_dedupe_keeps_distinct_txns():
    a = txn_in_paris("HOTEL PARIS", "200", 13, approval_no="111")
    b = txn_in_paris("HOTEL PARIS", "200", 13, approval_no="222")
    assert len(dedupe([a, b])) == 2


def test_pretrip_korean_air_included(paris_trip):
    t = make_txn("KOREAN AIR", Decimal("1200000"), "KRW", "2026-09-22T12:00:00+09:00")
    sel = select_trip_txns([t], paris_trip)
    assert [x.txn_id for x in sel] == [t.txn_id]


def test_pretrip_korean_air_row_mentions_pretrip(paris_trip, fx, tmp_path):
    t = make_txn("KOREAN AIR", Decimal("1200000"), "KRW", "2026-09-22T12:00:00+09:00")
    report = run_pipeline([t], paris_trip, fx, tmp_path, screenshot=shot_ok)
    assert len(report.rows) == 1
    row = report.rows[0]
    blob = (row["policy_reason"] + " " + row["notes"]).lower()
    assert "pre-trip" in blob or "pretrip" in blob


def test_domestic_gs25_day_before_excluded(paris_trip):
    t = make_txn("GS25", Decimal("5000"), "KRW", "2026-10-11T12:00:00+09:00")
    assert select_trip_txns([t], paris_trip) == []


def test_cancelled_positive_charge_excluded(paris_trip):
    t = txn_in_paris("HOTEL PARIS", "200", 13, status="cancelled")
    assert select_trip_txns([t], paris_trip) == []


def test_screenshot_runtime_error_flags_row(paris_trip, fx, tmp_path):
    good = txn_in_paris("HOTEL PARIS", "200", 13, approval_no="1")
    bad = txn_in_paris("CAFE DE FLORE", "30", 14, approval_no="2")

    def shot(txn, out_dir):
        if txn.txn_id == bad.txn_id:
            raise RuntimeError("boom")
        return shot_ok(txn, out_dir)

    report = run_pipeline([good, bad], paris_trip, fx, tmp_path, screenshot=shot)
    rows = {r["txn_id"]: r for r in report.rows}
    assert len(rows) == 2
    bad_row = rows[bad.txn_id]
    assert bad_row["policy_status"] == "FLAG"
    assert "missing screenshot" in bad_row["policy_reason"]
    assert "screenshot failed" in bad_row["notes"]
    assert rows[good.txn_id]["policy_status"] != "FLAG" or "missing screenshot" not in rows[good.txn_id]["policy_reason"]
    assert any(e["txn_id"] == bad.txn_id and e["stage"] == "screenshot" for e in report.errors)


def test_screenshot_auth_required_propagates(paris_trip, fx, tmp_path):
    t = txn_in_paris("HOTEL PARIS", "200", 13)

    def shot(txn, out_dir):
        raise AuthRequired("login expired")

    with pytest.raises(AuthRequired):
        run_pipeline([t], paris_trip, fx, tmp_path, screenshot=shot)


def test_ocr_mismatch_recorded_in_notes(paris_trip, fx, tmp_path):
    t = txn_in_paris("CAFE DE FLORE", "30", 14)

    def ocr(png, txn):
        return {"ok": False, "found_amount": None, "found_merchant": None, "notes": "amount not found"}

    report = run_pipeline([t], paris_trip, fx, tmp_path, screenshot=shot_ok, ocr=ocr)
    row = report.rows[0]
    assert "ocr mismatch" in row["notes"]
    assert row["ocr_ok"] == "False"


def test_ocr_ok_sets_flag(paris_trip, fx, tmp_path):
    t = txn_in_paris("CAFE DE FLORE", "30", 14)

    def ocr(png, txn):
        return {"ok": True}

    report = run_pipeline([t], paris_trip, fx, tmp_path, screenshot=shot_ok, ocr=ocr)
    assert report.rows[0]["ocr_ok"] == "True"


def test_sheet_sink_receives_header_then_all_rows(paris_trip, fx, tmp_path):
    a = txn_in_paris("HOTEL PARIS", "200", 13, approval_no="1")
    b = txn_in_paris("CAFE DE FLORE", "30", 14, approval_no="2")
    sink = SheetSink()
    report = run_pipeline([a, b], paris_trip, fx, tmp_path, screenshot=shot_ok, sheet=sink)
    assert sink.calls == ["ensure_header", "upsert"]
    assert len(sink.rows) == 2
    assert {r["txn_id"] for r in sink.rows} == {a.txn_id, b.txn_id}
    assert report.sheet == {"updated": 0, "appended": 2}
    for r in sink.rows:
        assert r["trip_id"] == "PAR-2026-10"
        assert r["city"] == "Paris"
        assert r["country"] == "FR"


def test_no_sheet_called_without_rows(paris_trip, fx, tmp_path):
    sink = SheetSink()
    report = run_pipeline([], paris_trip, fx, tmp_path, sheet=sink)
    assert sink.calls == []
    assert report.rows == []


def test_deel_items_excludes_fail_and_zero(paris_trip, fx, tmp_path):
    a = txn_in_paris("HOTEL PARIS", "1300", 13, approval_no="1")
    b = txn_in_paris("CAFE DE FLORE", "30", 14, approval_no="2")
    c = txn_in_paris("AXA ASSURANCE VOYAGE", "50", 13, approval_no="3")
    report = run_pipeline([a, b, c], paris_trip, fx, tmp_path, screenshot=shot_ok)
    rows = {r["txn_id"]: r for r in report.rows}
    assert rows[a.txn_id]["policy_status"] == "FLAG"
    assert rows[c.txn_id]["policy_status"] == "FAIL"
    assert c.txn_id not in {i["txn_id"] for i in deel_items(report.rows)}
    assert rows[b.txn_id]["policy_status"] == "PASS"
    items = deel_items(report.rows)
    ids = {i["txn_id"] for i in items}
    assert a.txn_id in ids
    assert b.txn_id in ids
    for i in items:
        assert isinstance(i["amount"], Decimal)
        assert i["amount"] > 0
        assert i["trip_id"] == "PAR-2026-10"
        assert len(i["date"]) == 10


def test_deel_items_drops_fail_rows_directly():
    rows = [
        {"txn_id": "x1", "category": "insurance", "amount": "50", "currency": "EUR",
         "approved_at": "2026-10-13T12:00:00+02:00", "merchant": "AXA", "trip_id": "T",
         "policy_status": "FAIL", "policy_reason": "insurance not reimbursable",
         "reimbursable": "50", "screenshot_url": ""},
        {"txn_id": "x2", "category": "meal", "amount": "0", "currency": "EUR",
         "approved_at": "2026-10-13T12:00:00+02:00", "merchant": "M", "trip_id": "T",
         "policy_status": "PASS", "policy_reason": "", "reimbursable": "0", "screenshot_url": ""},
    ]
    assert deel_items(rows) == []


def test_totals_sums_by_status_and_currency(paris_trip, fx, tmp_path):
    a = txn_in_paris("HOTEL PARIS", "400", 13, approval_no="1")
    b = txn_in_paris("CAFE DE FLORE", "30", 14, approval_no="2")
    c = txn_in_paris("CAFE LE PAUL", "20", 15, approval_no="3")
    report = run_pipeline([a, b, c], paris_trip, fx, tmp_path, screenshot=shot_ok)
    totals = report.totals()
    assert "FAIL" not in totals
    status_of = {r["txn_id"]: r["policy_status"] for r in report.rows}
    meal_total = Decimal("0")
    for r in report.rows:
        if r["category"] == "meal":
            meal_total += Decimal(r["reimbursable"])
    assert all(status_of[t.txn_id] == "PASS" for t in (a, b, c))
    assert totals["PASS"]["EUR"] == Decimal("400") + meal_total


def test_report_counts(paris_trip, fx, tmp_path):
    a = txn_in_paris("HOTEL PARIS", "200", 13, approval_no="1")
    dup = make_txn("HOTEL PARIS", Decimal("200"), "EUR", a.approved_at.isoformat(), approval_no=a.approval_no)
    domestic = make_txn("GS25", Decimal("5000"), "KRW", "2026-10-11T12:00:00+09:00")
    report = run_pipeline([a, dup, domestic], paris_trip, fx, tmp_path, screenshot=shot_ok)
    assert report.fetched == 3
    assert report.in_trip == 1
    assert len(report.rows) == 1
