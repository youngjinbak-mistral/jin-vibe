# 서울 아파트 시세 모니터 (Seoul apartment housing monitor)

Single-user web app for comparing 매매 (buy) vs 전세 vs 월세 on apartment complexes in east/central Seoul. It keeps a registry of watched complexes, records prices as separate, versioned series, and mirrors new observations into your existing housing Google Sheet without touching your own rows.

Status: **Phase 1** (registry, manual import, price-history charts, one-time Google Sheet connection with append-only versioned sync). Phase 2 (MOLIT 실거래가 scheduled sync) and Phase 3 (buy/rent calculator + alerts) are not built yet.

## Run locally

```bash
cd housing-monitor
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export HM_MASTER_KEY=$(python -m app.keygen)
export HM_SESSION_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
export HM_APP_PASSWORD='choose-one'
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Run the tests with `python -m pytest -q`.

| Variable | Purpose |
|---|---|
| `HM_MASTER_KEY` | Required. Fernet key that encrypts every stored secret (Google refresh token, client secret, data.go.kr key). Keep it in your platform's secret manager. The app refuses to start without it. |
| `HM_SESSION_SECRET` | Signs the browser session cookie. Set it so logins survive restarts. |
| `HM_APP_PASSWORD` | Optional login gate for the UI. Set it whenever the app is reachable by anyone but you. |
| `HM_PUBLIC_BASE_URL` | Base URL used to build the Google OAuth redirect URI. |
| `HM_DATABASE_URL` | SQLAlchemy URL. Defaults to local SQLite; PostgreSQL works as well (amounts use `BIGINT`). |
| `HM_GOOGLE_CLIENT_ID`, `HM_GOOGLE_CLIENT_SECRET`, `HM_MOLIT_SERVICE_KEY` | Optional. When set, these environment variables take precedence over the values entered in Settings. |

## Data rules (enforced in code and DB constraints)

- **Three separate series.** Records are keyed by complex, 전용 59㎡ or 84㎡, and 매매 / 전세 / 월세. A `CHECK` constraint enforces the amount fields for each type: 매매 has only `price_krw`, 전세 has only `deposit_krw`, and 월세 must have both `deposit_krw` and `monthly_rent_krw`. Charts and the series API always return a single transaction type.
- **Amounts.** Stored as KRW integers. The UI shows them in 억/만원 and accepts input like `12억 5,000`, `5,000` (만원), or `1억/250`.
- **전용 vs 공급.** These are separate columns. An 전용 value that falls outside the selected size class (for example a 112㎡ supply area typed into the 전용 field) is rejected.
- **Record fields.** Each record carries amount, type, nature (실거래/호가), source name, URL and ID, contract date, report/capture date, cancellation/amendment status, and the raw pasted snippet.
- **Freshness.** Each series has an expected update interval (defaults: 실거래 45 days, 호가 14 days, editable in Settings). A series that misses its interval shows `갱신 지연` (stale).
- **Dedup:**
  - With a provider ID: identical data counts as a duplicate. Changed data becomes a new version (same `record_uid`, `version + 1`); the old row is kept, only its `is_current` flag changes. A replay of an older version goes to review.
  - Without a provider ID: matched on a SHA-256 fingerprint of the full field set.
  - Partial matches (for example same price and floor but a different date) go to the **검토 대기** (review) queue and are never merged automatically. You then choose: separate deal, new version, or discard.
- **추정 (estimates).** Records and complex fields flagged as estimates are labeled 추정 everywhere they appear. Phase 3 alerts will ignore them.

## Asking prices (Naver 부동산 / 호갱노노)

Neither site offers an official API or export to individual users, so the app never fetches or scrapes them. You paste the listing text and/or link. `app/listing_parser.py` extracts complex, size, type, price, area, floor, date and listing ID offline, then shows a pre-filled form. Nothing is saved until you tick the confirmation box. The link is stored only as the record's source.

## Google Sheet sync (append-only)

1. Create a Google OAuth client (type: web application) and register the redirect URI shown in Settings. Enter the client ID and secret in Settings; they are stored encrypted.
2. Click **Google 계정 연결** once. Requested scopes: `openid email https://www.googleapis.com/auth/spreadsheets`. The OAuth flow uses PKCE and a state check. The refresh token is encrypted with `HM_MASTER_KEY`. Access tokens refresh automatically. If Google reports `invalid_grant` (expired or revoked token), the stored token is deleted and the UI asks you to connect again.
3. Paste the workbook URL. The app shows the **connected account email** and the **workbook title**, and you retype both to confirm. Before that, nothing is written. A URL that can't be opened stops the flow; the app never falls back to another workbook.
4. Pick the tab and header row. The app reads the existing headers, reuses matching columns (for example `단지`), and proposes new observation columns to the right of your last header. It refuses if those target columns already contain data. You approve the plan before the headers are written. If no existing tab fits, it proposes a new `관측기록(앱)` tab, created only after you approve.
5. Every sync, including each batch within a sync, re-checks that:
   - the live account email and workbook title still match what you confirmed,
   - the tab still exists with the same sheet ID,
   - your original header row is unchanged.

   If any check fails, it stops and shows the reason. Rows are written with `values.update` strictly below the last used row (never `:append`, which can insert rows inside your data). It never edits, deletes, or reorders existing rows.
6. Each row carries `관측ID` (the record UID) and `버전` (version). A local receipt table and a pre-write scan of the sheet's ID and version columns prevent duplicate rows on retries. When source data changes, a new version is appended; the old row is never rewritten.

Credentials never appear in templates, the sheet, logs, or exports. The settings page only shows `암호화 저장됨` (stored encrypted), `환경변수로 설정됨` (set via environment variable), or `미설정` (not set). The app never asks for a password for any third-party service.

## Defaults (editable in Settings)

- Watch areas:
  - 광진구: 광장동, 구의동, 자양동 (아차산역 area)
  - 성동구 up to 옥수동 as the western edge
  - plus 동대문·중랑·송파·강동구
- Seeded complex: 래미안 파크스위트 (광진구 구의동, 아차산역, 2018, 854 units, from public listings). Please verify these figures yourself.
- Commute destinations: 판교, 수원, 공덕 (entered manually).
- Daycare anchor: 파크빌, enrollment 2027-03.

## Layout

```
app/main.py            FastAPI routes, CSRF, optional password gate
app/models.py          SQLAlchemy models + DB constraints
app/records.py         validation, fingerprint dedup, versioning, review queue, freshness
app/listing_parser.py  offline paste parser (no network)
app/sheets.py          Google Sheets REST client + column planning
app/sheet_sync.py      OAuth token provider, destination verification, append-only sync
app/secrets_store.py   Fernet-encrypted secret storage
app/static/chart.js    dependency-free SVG chart (one transaction type at a time)
tests/                 pytest suite, incl. an in-memory fake of Google OAuth/Sheets
```
