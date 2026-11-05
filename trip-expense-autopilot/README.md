# Trip Expense Autopilot (`tea`)

Turns Hana Card (하나카드) charges from a business trip into a policy-checked Google Sheet with a screenshot per payment, then fills the Deel expense form. **Nothing is submitted to Deel unless you run `--approve` and type `yes`.**

```
Hana Card ──► normalize ──► trip filter ──► screenshot + OCR check ──► policy engine ──► Google Sheet + Drive
 (CODEF API | web | CSV)                       (Playwright, mistral-ocr)   (Mistral Expense & Travel policy)
                                                                                         │
                                                         Deel (EOR) form fill ◄──────────┘  draft by default, submit only with --approve
```

## What it does

| Step | How |
|---|---|
| Fetch card spend | CODEF personal-card approval API (`0313` Hana Card), Hana Card website (Playwright, your own login + 2FA), or a Hana Card 이용내역 CSV export (CP949/UTF-8) |
| Select trip spend | Trip window + destinations; also pre-trip flight/train/hotel/visa bookings up to 60 days before |
| Screenshot each payment | Opens the transaction detail on the Hana Card site, **masks card number and name**, saves PNG |
| Verify screenshot | Mistral OCR reads the PNG and checks amount + merchant match the card record |
| Policy check | Deterministic rules from the Notion *Expense & Travel policy*: hotel nightly caps per city, daily meal caps per country (computed on the **local** day, not KST), long-stay 50% meal rule, first/last-day 17:30/13:00 rule, insurance not reimbursable, visa/ESTA reimbursable, gift caps, US car rental $75/day. Result: `PASS` / `FLAG` (with reimbursable amount capped) / `FAIL` |
| Classify merchants | Keyword rules first; unknown merchants are classified by **Mistral Large 4 and GLM-5.3 in parallel**, and a disagreement becomes `other` → `FLAG`, reimbursable 0 |
| Record | Upserts one row per transaction into the Google Sheet (idempotent by `txn_id`), uploads screenshots to Drive |
| Deel | Fills the EOR "Add expense" form (category, amount, currency, date, description with `[tea:<txn_id>]`, screenshot) and saves a screenshot of the filled form. `--approve` clicks Submit |

## Safety rules built in

- Submit to Deel only with `tea deel --approve` **and** typing `yes` after the totals are printed.
- `FAIL` rows, rows with 0 reimbursable, and rows without a screenshot are never submitted.
- Local SQLite ledger (`~/.tea/ledger.db`) with `BEGIN IMMEDIATE` locking: a `txn_id` can be submitted once. If the process dies between clicking Submit and seeing the confirmation, the row stays `submitting` and is **not retried** until you verify it on Deel.
- CAPTCHA or expired session → stops with `CaptchaRequired` / `AuthRequired`. It never tries to solve or bypass them.
- Card number and holder name are masked before the screenshot. Sessions are stored at `~/.tea/*_state.json` with mode `0600`. Nothing is exposed on the network.

## Setup

```bash
cd trip-expense-autopilot
pip install playwright httpx google-auth pydantic pytest
python -m playwright install chromium
```

Environment (put in your shell or a local secret manager, never commit):

| Variable | Needed for |
|---|---|
| `MISTRAL_API_KEY` | LLM merchant classification + OCR check (optional; `--no-llm` disables) |
| `CODEF_CLIENT_ID`, `CODEF_CLIENT_SECRET`, `CODEF_CONNECTED_ID` | `--source codef` (register Hana Card once in CODEF to get a connectedId) |
| `TEA_GOOGLE_CREDENTIALS` | path to a service-account or authorized-user JSON with Sheets + `drive.file` scopes |
| `TEA_SHEET_ID` | target spreadsheet id (ledger sheet already created: *Trip Expense Autopilot - Ledger*) |
| `TEA_SHEET_TAB` | tab name, default `Ledger` |
| `TEA_DRIVE_FOLDER_ID` | optional Drive folder for screenshots |

Selectors for the real Hana Card and Deel pages live in `selectors/hanacard.json` and `selectors/deel.json`. **They are placeholders and must be calibrated once against the live sites** (open DevTools, copy selectors). If a selector stops matching, the run stops with `SelectorDrift` instead of guessing.

## Usage

```bash
# 1. describe the trip
cat > trip.json <<'EOF'
{"id": "PAR-2026-10", "start": "2026-10-12T10:00:00+09:00", "end": "2026-10-17T18:00:00+02:00",
 "departure_at": "2026-10-12T10:00:00+09:00", "return_arrival_at": "2026-10-18T14:30:00+09:00",
 "stay_type": "hotel",
 "destinations": [{"city": "Paris", "country": "FR", "from": "2026-10-12T00:00:00+02:00", "to": "2026-10-17T23:59:00+02:00"}]}
EOF

# 2. one-time logins (opens a real browser; you do 2FA yourself)
python -m tea login hana
python -m tea login deel

# 3. fetch, screenshot, check policy, write to the sheet
python -m tea run --trip trip.json --source web --headed          # or --source codef --screenshots, or --source csv --csv export.csv
python -m tea run --trip trip.json --source csv --csv export.csv --dry-run   # local only, no Google writes

# 4. Deel: fill forms for review (no submit)
python -m tea deel --trip trip.json --headed
# 5. submit PASS items after review (add --include-flagged to also send FLAG rows at their capped amount)
python -m tea deel --trip trip.json --approve
```

## QA

```bash
pytest tests --ignore=tests/e2e        # 176 unit/integration tests, no network
pytest tests/e2e                       # 45 Playwright E2E tests against local mock Hana Card + Deel sites
```

E2E matrix: Chromium desktop, Firefox desktop, WebKit (Safari) desktop, Pixel 7, iPhone 15, Galaxy S9+. Failure scenarios covered: expired Hana session, CAPTCHA, selector drift, empty history, not logged in, Deel session expired, Deel form rejection, slow Deel confirmation, duplicate submission, FAIL item with `--approve`, crash between Submit and confirmation, concurrent runs.

## How it was built (multi-model)

`orchestration/` contains the dispatcher used to build this. Claude Opus 5.5 acted as orchestrator: it wrote the spec, reviewed the code, did integration and debugging, and assigned subtasks:

| Subtask | Model | Outcome |
|---|---|---|
| Policy engine, trip/timezone, classifier | Mistral Large 4 | Good. A second pass fixed timezone, word-boundary and nights bugs found in review |
| Card sources (CODEF, CSV, Hana web), mock sites, E2E tests, IO fixes | GLM-5.3 | Fastest (12–68s), solid. Some selector/test-harness bugs fixed during integration |
| Sheets/ledger/Deel/OCR first draft | Codestral | Fast but buggy (wrong batchUpdate rows, float vs Decimal), so it was **reassigned to GLM-5.3** |
| Adversarial unit tests | Claude Opus 5.5 + Mistral Large 4 | Opus wrote the strongest tests. Sonnet 5.5 timed out on every call (gateway 30s first-byte limit), so it was **reassigned to Opus**, and large prompts were split |
| Code review (safety) | Mistral Large 4 (Opus timed out) | Found the crash-after-submit duplicate window, a ledger race, and out-of-trip reimbursement. All fixed, with tests |
| Merchant classification at runtime | Mistral Large 4 + GLM-5.3 ensemble | 10/12 correct on a hard merchant set. Disagreements fall back safely to FLAG |
| Receipt/screenshot OCR | mistral-ocr-latest | 0.8s per screenshot, read merchant/amount/date/approval no correctly, masked fields stayed hidden |

Per-call latency and token usage are logged by the dispatcher in `orchestration/out/model_runs.jsonl` (not committed).

## Known limits

- Real Hana Card and Deel selectors need a one-time calibration (see above).
- Deel EOR has no personal API, so this uses browser automation. Deel UI changes will surface as `SelectorDrift` and need selector updates.
- CODEF needs your own CODEF account; Hana Card login via CODEF uses your Hana credentials and is subject to their terms.
- Flights/trains are always FLAG ("verify class & booking channel"). Fare class is not on the card record.
