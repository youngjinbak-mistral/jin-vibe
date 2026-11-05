from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .models import AuthRequired, CaptchaRequired, PolicyResult, Transaction
from .policy.classify import classify_with_meta
from .policy.rules import evaluate
from .sheets import row_for
from .trip import Trip


class Screenshotter(Protocol):
    def __call__(self, txn: Transaction, out_dir: Path) -> Path: ...


class Uploader(Protocol):
    def upload_png(self, path: Path, name: str) -> str: ...


class SheetSink(Protocol):
    def ensure_header(self) -> None: ...
    def upsert(self, rows: list[dict]) -> dict[str, int]: ...


@dataclass
class RunReport:
    fetched: int = 0
    in_trip: int = 0
    rows: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    sheet: dict[str, int] = field(default_factory=dict)

    def totals(self) -> dict[str, dict[str, Decimal]]:
        out: dict[str, dict[str, Decimal]] = {}
        for r in self.rows:
            if r["policy_status"] == "FAIL":
                continue
            bucket = out.setdefault(r["policy_status"], {})
            bucket[r["currency"]] = bucket.get(r["currency"], Decimal("0")) + Decimal(r["reimbursable"])
        return out


def dedupe(txns: Iterable[Transaction]) -> list[Transaction]:
    seen: dict[str, Transaction] = {}
    for t in txns:
        seen[t.txn_id] = t
    return list(seen.values())


PRE_TRIP_CATEGORIES = ("flight", "train", "visa", "hotel")


def select_trip_txns(txns: list[Transaction], trip: Trip, pre_trip_days: int = 60) -> list[Transaction]:
    selected = []
    start = trip.start if trip.start.tzinfo else trip.start.replace(tzinfo=trip.local_dt(trip.start).tzinfo)
    window_start = start - timedelta(days=pre_trip_days)
    for t in txns:
        if t.status == "cancelled" and t.amount >= 0:
            continue
        if trip.in_trip(t):
            selected.append(t)
            continue
        if window_start <= t.approved_at < start and classify_with_meta(t)["category"] in PRE_TRIP_CATEGORIES:
            selected.append(t)
    return selected


def run_pipeline(
    txns: list[Transaction],
    trip: Trip,
    fx: Any,
    out_dir: Path,
    llm: Any = None,
    screenshot: Callable[[Transaction, Path], Path] | None = None,
    ocr: Callable[[Path, Transaction], dict] | None = None,
    uploader: Uploader | None = None,
    sheet: SheetSink | None = None,
) -> RunReport:
    report = RunReport(fetched=len(txns))
    out_dir.mkdir(parents=True, exist_ok=True)
    txns = select_trip_txns(dedupe(txns), trip)
    report.in_trip = len(txns)

    categories: dict[str, str] = {}
    for t in txns:
        categories[t.txn_id] = classify_with_meta(t, llm)["category"]

    results: dict[str, PolicyResult] = evaluate(txns, trip, fx, categories)

    for t in sorted(txns, key=lambda x: x.approved_at):
        res = results.get(t.txn_id)
        if res is None:
            continue
        shot_url, ocr_ok, notes = "", False, []
        png: Path | None = None
        if screenshot is not None:
            try:
                png = screenshot(t, out_dir)
            except (AuthRequired, CaptchaRequired):
                raise
            except Exception as exc:
                notes.append(f"screenshot failed: {type(exc).__name__}")
                report.errors.append({"txn_id": t.txn_id, "stage": "screenshot", "error": str(exc)})
        if png is not None and ocr is not None:
            try:
                check = ocr(png, t)
                ocr_ok = bool(check.get("ok"))
                if not ocr_ok:
                    notes.append(f"ocr mismatch: {check.get('notes', '')}")
            except Exception as exc:
                notes.append(f"ocr failed: {type(exc).__name__}")
                report.errors.append({"txn_id": t.txn_id, "stage": "ocr", "error": str(exc)})
        if png is not None and uploader is not None:
            try:
                shot_url = uploader.upload_png(png, png.name)
            except Exception as exc:
                notes.append(f"upload failed: {type(exc).__name__}")
                report.errors.append({"txn_id": t.txn_id, "stage": "upload", "error": str(exc)})
        elif png is not None:
            shot_url = str(png)
        city, country = trip.location_for(t.approved_at)
        row = row_for(t, res, trip.id, city, country, shot_url, ocr_ok)
        if png is None and res.status == "PASS" and screenshot is not None:
            row["policy_status"] = "FLAG"
            row["policy_reason"] = "; ".join(filter(None, [row["policy_reason"], "missing screenshot"]))
        row["notes"] = "; ".join(notes)
        report.rows.append(row)

    if sheet is not None and report.rows:
        sheet.ensure_header()
        report.sheet = sheet.upsert(report.rows)
    return report


def deel_items(rows: list[dict]) -> list[dict]:
    items = []
    for r in rows:
        if r.get("policy_status") == "FAIL":
            continue
        amount = Decimal(r["reimbursable"])
        if amount <= 0:
            continue
        items.append(
            {
                "txn_id": r["txn_id"],
                "category": r["category"],
                "amount": amount,
                "currency": r["currency"],
                "date": r["approved_at"][:10],
                "merchant": r["merchant"],
                "trip_id": r["trip_id"],
                "policy_status": r["policy_status"],
                "policy_reason": r["policy_reason"],
                "screenshot": r.get("screenshot_path") or r.get("screenshot_url", ""),
            }
        )
    return items
