# Trip Expense Autopilot — Spec

Python 3.12 package `tea`. Stdlib + `playwright`, `httpx`, `google-auth`, `cryptography`, `pydantic` only. Everything runs locally on the user's machine. No server is exposed. Secrets come from env vars or the OS keychain and are never logged.

## Pipeline

```
Hana Card (CODEF API | Playwright web | CSV export)
  -> normalize -> Transaction
  -> trip filter (trip.yaml: dates, cities, home country)
  -> evidence: screenshot of the txn detail screen (Playwright), OCR cross-check (mistral-ocr)
  -> policy engine (deterministic rules from Mistral Expense & Travel policy) + LLM category/second opinion
  -> Google Sheet upsert (idempotent by txn_id) + Drive upload of screenshot
  -> Deel (EOR employee) web form fill as DRAFT; final submit only with explicit `--approve`
```

## Modules

### tea/models.py
```python
@dataclass(frozen=True)
class Transaction:
    txn_id: str            # stable: sha1(card_last4|approval_no|approved_at iso|amount|currency)[:16] if not given
    approved_at: datetime  # tz-aware, Asia/Seoul for domestic, as given for overseas
    merchant: str
    amount: Decimal        # original currency amount, positive for charge, negative for refund/cancel
    currency: str          # ISO 4217
    amount_krw: Decimal | None
    card_last4: str
    approval_no: str
    status: str            # "approved" | "cancelled" | "partial_cancel"
    country: str | None    # ISO 3166 alpha-2 if known
    mcc_category: str | None
    raw: dict
@dataclass
class PolicyResult:
    status: str            # "PASS" | "FLAG" | "FAIL"
    category: str          # hotel|meal|flight|train|taxi|car_rental|mileage|visa|insurance|gift|equipment|other
    reasons: list[str]
    cap: Decimal | None
    cap_currency: str | None
    reimbursable: Decimal  # amount to claim in original currency (min(amount, remaining cap) for meals/hotel)
```

### tea/sources/codef.py
CODEF personal card approval list `POST /v1/kr/card/p/account/approval-list` (product KR_CD_P_002), organization `0313` (Hana Card).
- `CodefClient(client_id, client_secret, base_url="https://api.codef.io", http=httpx.Client)`; OAuth token from `https://oauth.codef.io/oauth/token` (client_credentials, basic auth), cached until expiry.
- `fetch_approvals(connected_id, start: date, end: date, inquiry_type="1", member_store_info_type="1") -> list[dict]`.
- CODEF responses may be URL-encoded JSON text: `urllib.parse.unquote_plus` then json.loads. `result.code == "CF-00000"` is success; else raise `SourceError(code, message)`.
- `normalize_codef(row) -> Transaction`: keys `resUsedDate` (YYYYMMDD), `resUsedTime` (HHMMSS), `resMemberStoreName`, `resUsedAmount`, `resAccountCurrency` (default KRW), `resCardNo` (masked, take last 4 digits), `resApprovalNo`, `resCancelYN` ("0" normal, "1" cancelled, "2" partial, "3" rejected → skip), `resCancelAmount`, `resKRWAmt`, `resMemberStoreType`, `resHomeForeignType` ("1" domestic, "2" overseas), `resMemberStoreAddr`. Missing keys tolerated. Amounts may contain commas.
- Rate-limit: max 1 req/s; on HTTP 429/5xx retry 3x with backoff.

### tea/sources/hanacard_web.py
Playwright adapter. Selectors come from `selectors/hanacard.json` so they can be updated without code changes.
- `login(page)`: opens login URL, then WAITS for the user to finish login + 2FA (headed). Detect success by `selectors.logged_in`. Timeout → `AuthRequired`.
- Session persisted via `storage_state` at `~/.tea/hana_state.json`, permissions 0600.
- `list_transactions(page, start, end) -> list[Transaction]` reads table rows (`selectors.row`, cells by `selectors.cells.*`), paginates via `selectors.next_page` until disabled.
- `screenshot_transaction(page, txn, out_dir) -> Path`: opens detail (`selectors.detail_link` filtered by approval no), screenshots `selectors.detail_panel` element, masks `selectors.mask` (card number, name) with CSS before capture. File name `{txn_id}.png`.
- Detect `selectors.session_expired` / captcha → raise `AuthRequired` / `CaptchaRequired` (never try to solve).

### tea/sources/csv_import.py
Hana Card "이용내역" export (xlsx saved as CSV, UTF-8 or CP949). Columns: 이용일자, 이용시간, 가맹점명, 이용금액, 통화, 원화금액, 승인번호, 카드번호, 취소여부, 국가. Auto-detect encoding.

### tea/trip.py
`Trip` from YAML/JSON: `id, start (datetime w/ tz), end, destinations: [{city, country, from, to}], home_country="KR", stay_type: hotel|long_term, departure_at, return_arrival_at`.
- `in_trip(txn)`: approved_at within [start - 1 day for pre-booking? NO → only within start..end] OR txn merchant in `extra_include` list; exclude `extra_exclude` merchants.
- `location_for(dt) -> (city, country)`.

### tea/fx.py
`FxRates` interface `rate(date, from_ccy, to_ccy) -> Decimal`. `StaticFx(table)` for tests, `FrankfurterFx` (api.frankfurter.app, cached on disk). If the card provides `amount_krw`, prefer it for KRW conversions.

### tea/policy/rules.py — deterministic rules (source: Notion "Expense & Travel policy")
Hotel nightly caps (per night, all taxes incl.):
UK global £150; London £260; Europe global €180; Paris €230; Bruxelles €250; Amsterdam €250; UAE AED 1000; Morocco MAD 1500; USA global $280; NYC $350; Palo Alto/San Francisco $475; Canada global CAD 280; Toronto CAD 350; Montréal CAD 350; Singapore SGD 400.
Meals daily caps (food+drinks+tips, sum per calendar day):
UK £50; Morocco MAD 320; Europe €45; Switzerland CHF 50; Poland PLN 150; USA $75 (SF, NYC $100); Canada CAD 75 (Toronto, Montréal CAD 100); Singapore SGD 55.
- long_term stay → meal caps × 0.5.
- First day counts only if departure before 17:30; last day only if arrival after 13:00; otherwise meals on that day → FLAG "day not eligible".
- Over cap → FLAG with reimbursable = remaining cap; never FAIL for over-cap (policy allows justified exceptions). Hotel over cap and stay > 10 nights → FAIL ("no out of policy exceptions > 10 days").
- insurance → FAIL (company covers). visa/ESTA/ETA → PASS. flight/train → FLAG "verify class & booking channel" unless amount ≤ cap? (no cap) → PASS with note. taxi → PASS with note "justify if public transport available". Gift for staying with friend: ≤ €50 (<7 nights) / €300 (≥7 nights) with GBP 45/260, USD 60/355, SGD 75/440.
- Unknown country/city → FLAG "no cap defined".
- Domestic (country == home_country) and not in trip → excluded upstream.
- Region mapping: Europe = EU/EEA + UK separate, CH separate, PL separate, MA, AE, US, CA, SG.
- Cap currency vs txn currency differ → convert txn to cap currency via FxRates.

### tea/policy/classify.py
`classify(txn) -> category`: keyword/MCC heuristics first (hotel, airbnb, booking.com, marriott, 호텔; uber, taxi, bolt, g7; sncf, eurostar, trainline, db bahn; air, airlines, 항공; restaurant, cafe, bistro, starbucks, boulangerie, 식당; esta, visa, vfs; insurance, 보험). If unresolved, call LLM (`LLMClient.complete_json`) with model `mistral-large-4`; on disagreement with second model `zai-glm-5-3` → category "other", status FLAG.

### tea/evidence/ocr.py
`ocr_check(png_path, txn) -> dict(ok: bool, found_amount, found_merchant, notes)` using Mistral OCR (`mistral-ocr-latest`, document type image_url data URI). OK if amount (normalized digits) and ≥60% of merchant tokens appear.

### tea/sheets.py
`SheetsClient(spreadsheet_id, session)` via Google Sheets REST v4 with `google.auth` credentials.
- Header row fixed (see HEADER constant below). `upsert(rows: list[dict])`: read column A, update existing rows by txn_id, append new. Batch ≤ 500 rows per request. Retry 429/5xx.
HEADER = txn_id, approved_at, merchant, amount, currency, amount_krw, card_last4, category, trip_id, city, country, screenshot_url, ocr_ok, policy_status, policy_reason, policy_cap, reimbursable, submit_status, deel_ref, notes

### tea/deel_web.py
Playwright filler for Deel EOR "Add expense" form. Selectors from `selectors/deel.json`.
- `prepare_expense(page, item, screenshot) -> "drafted"`: open add-expense, fill category, amount, currency, date, description (`"{merchant} — {trip_id} — {policy_reason}"`), upload screenshot, then STOP (do not click submit) unless `approve=True`.
- `submit(page)` only invoked when `approve=True`; returns reference id read from `selectors.confirmation_ref`.
- Idempotency: `Ledger` (sqlite at ~/.tea/ledger.db) keyed by txn_id; never submit the same txn twice; status transitions new→drafted→submitted, or →skipped.
- Only PASS and FLAG items with user approval are submitted; FAIL never.

### tea/cli.py
`python -m tea run --trip trip.yaml --source codef|web|csv [--csv file] [--dry-run]` → fetch, filter, evidence, policy, sheet.
`python -m tea deel --trip trip.yaml [--approve]` → draft (default) or submit approved rows.
`python -m tea login hana|deel` → headed login, store state.

## Safety
- No credential ever written to logs/sheet. Card numbers masked to last 4.
- Final Deel submit requires `--approve` flag AND interactive y/N confirmation listing totals.
- Browser automation never solves CAPTCHA, never bypasses 2FA.
