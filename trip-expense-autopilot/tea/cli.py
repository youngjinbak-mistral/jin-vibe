from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

HOME = Path(os.environ.get("TEA_HOME", "~/.tea")).expanduser()
ROOT = Path(__file__).resolve().parent.parent
SELECTORS = ROOT / "selectors"


def _window(trip):
    return (trip.start - timedelta(days=60)).date(), trip.end.date()


def _require_env(*names: str) -> list[str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(missing)} (see README)")
    return [os.environ[n] for n in names]


def _fetch(args, trip):
    start, end = _window(trip)
    if args.source == "csv":
        from .sources.csv_import import load_csv

        return load_csv(args.csv)
    from .sources.codef import CodefClient, normalize_codef

    client_id, client_secret, connected_id = _require_env("CODEF_CLIENT_ID", "CODEF_CLIENT_SECRET", "CODEF_CONNECTED_ID")
    client = CodefClient(client_id, client_secret, base_url=os.environ.get("CODEF_BASE_URL", "https://api.codef.io"))
    rows = client.fetch_approvals(connected_id, start, end)
    return [t for t in (normalize_codef(r) for r in rows) if t is not None]


def _print_report(report) -> None:
    print(f"fetched={report.fetched} in_trip={report.in_trip} rows={len(report.rows)} errors={len(report.errors)} sheet={report.sheet}")
    for r in report.rows:
        print(f"  {r['policy_status']:4} {r['category']:16} {r['amount']:>12} {r['currency']} -> {r['reimbursable']:>10}  {r['merchant'][:40]}  {r['policy_reason']}")
    for status, by_ccy in report.totals().items():
        print(f"  total {status}: " + ", ".join(f"{v} {k}" for k, v in by_ccy.items()))


def _google_sinks():
    import httpx

    from .drive import DriveUploader
    from .google_auth import token_provider
    from .sheets import SheetsClient

    (creds_path,) = _require_env("TEA_GOOGLE_CREDENTIALS")
    tok = token_provider(creds_path)
    client = httpx.Client(timeout=60)
    sheet = SheetsClient(os.environ["TEA_SHEET_ID"], client, tok, sheet_name=os.environ.get("TEA_SHEET_TAB", "Ledger"))
    uploader = DriveUploader(client, tok, folder_id=os.environ.get("TEA_DRIVE_FOLDER_ID"))
    return sheet, uploader


def cmd_run(args) -> int:
    from .fx import FrankfurterFx
    from .pipeline import run_pipeline
    from .trip import Trip

    trip = Trip.load(args.trip)
    use_llm = bool(os.environ.get("MISTRAL_API_KEY")) and not args.no_llm
    llm = None
    if use_llm:
        from .llm import MistralLLM

        llm = MistralLLM(os.environ["MISTRAL_API_KEY"])
    sheet = uploader = None
    if not args.dry_run and os.environ.get("TEA_SHEET_ID"):
        sheet, uploader = _google_sinks()
    out_dir = HOME / "runs" / trip.id
    fx = FrankfurterFx(HOME / "fx")

    if args.source != "web" and not args.screenshots:
        report = run_pipeline(_fetch(args, trip), trip, fx, out_dir, llm=llm, uploader=uploader, sheet=sheet)
    else:
        from playwright.sync_api import sync_playwright

        from .sources.hanacard_web import HanaCardWeb

        state = HOME / "hana_state.json"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            ctx = browser.new_context(storage_state=str(state) if state.exists() else None, locale="ko-KR")
            page = ctx.new_page()
            hana = HanaCardWeb(SELECTORS / "hanacard.json", state_path=state)
            start, end = _window(trip)
            listed = hana.list_transactions(page, start, end)
            txns = listed if args.source == "web" else _fetch(args, trip)
            ocr = None
            if use_llm:
                import httpx

                from .evidence.ocr import MistralOcrClient, ocr_check

                oc = MistralOcrClient(os.environ["MISTRAL_API_KEY"], httpx.Client(timeout=60))
                ocr = lambda png, t: ocr_check(png, t, oc)
            report = run_pipeline(
                txns, trip, fx, out_dir, llm=llm,
                screenshot=lambda t, out: hana.screenshot_transaction(page, t, out),
                ocr=ocr, uploader=uploader, sheet=sheet,
            )
            ctx.close()
    (out_dir / "rows.json").write_text(json.dumps(report.rows, ensure_ascii=False, indent=1))
    _print_report(report)
    return 0


def cmd_deel(args) -> int:
    from .deel_web import DeelWeb
    from .ledger import Ledger
    from .pipeline import deel_items
    from .trip import Trip

    trip = Trip.load(args.trip)
    out_dir = HOME / "runs" / trip.id
    items = deel_items(json.loads((out_dir / "rows.json").read_text()))
    if not args.include_flagged:
        items = [i for i in items if i["policy_status"] == "PASS"]
    totals: dict[str, Decimal] = {}
    for i in items:
        totals[i["currency"]] = totals.get(i["currency"], Decimal("0")) + i["amount"]
    print(f"{len(items)} expenses: " + ", ".join(f"{v} {k}" for k, v in totals.items()))
    for i in items:
        print(f"  {i['policy_status']:4} {i['date']} {i['amount']:>10} {i['currency']} {i['category']:16} {i['merchant'][:40]}")
    if args.approve:
        answer = input("Submit these expenses to Deel? This cannot be undone. Type 'yes': ")
        if answer.strip().lower() != "yes":
            print("aborted")
            return 1
    from playwright.sync_api import sync_playwright

    state = HOME / "deel_state.json"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(storage_state=str(state) if state.exists() else None)
        page = ctx.new_page()
        with Ledger(HOME / "ledger.db") as ledger:
            deel = DeelWeb(SELECTORS / "deel.json", ledger, out_dir=out_dir / "deel")
            for i in items:
                shot = out_dir / f"{i['txn_id']}.png"
                print(i["txn_id"], deel.prepare_expense(page, i, shot, approve=args.approve))
    return 0


def cmd_login(args) -> int:
    from playwright.sync_api import sync_playwright

    HOME.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        if args.service == "hana":
            from .sources.hanacard_web import HanaCardWeb

            HanaCardWeb(SELECTORS / "hanacard.json", state_path=HOME / "hana_state.json").login(page)
        else:
            sel = json.loads((SELECTORS / "deel.json").read_text())
            page.goto(sel["expenses_url"])
            input("Log in to Deel in the opened browser, then press Enter here...")
            path = HOME / "deel_state.json"
            path.write_text(json.dumps(ctx.storage_state()))
            os.chmod(path, 0o600)
    print("session saved")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tea", description="Trip Expense Autopilot")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--trip", required=True)
    r.add_argument("--source", choices=["codef", "web", "csv"], required=True)
    r.add_argument("--csv")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--screenshots", action="store_true")
    r.add_argument("--headed", action="store_true")
    r.add_argument("--no-llm", action="store_true")
    d = sub.add_parser("deel")
    d.add_argument("--trip", required=True)
    d.add_argument("--approve", action="store_true")
    d.add_argument("--include-flagged", action="store_true")
    d.add_argument("--headed", action="store_true")
    lg = sub.add_parser("login")
    lg.add_argument("service", choices=["hana", "deel"])
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if args.command == "run" and args.source == "csv" and not args.csv:
        p.error("--csv is required with --source csv")
    return {"run": cmd_run, "deel": cmd_deel, "login": cmd_login}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
