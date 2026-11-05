import time
from typing import Any, Callable
import httpx
from tea.models import Transaction, PolicyResult

HEADER = [
    "txn_id", "approved_at", "merchant", "amount", "currency", "amount_krw",
    "card_last4", "category", "trip_id", "city", "country", "screenshot_url",
    "ocr_ok", "policy_status", "policy_reason", "policy_cap", "reimbursable",
    "submit_status", "deel_ref", "notes"
]

_RETRYABLE = {429, 500, 502, 503, 504}


class SheetsClient:
    def __init__(
        self,
        spreadsheet_id: str,
        http: httpx.Client,
        token_provider: Callable[[], str],
        sheet_name: str = 'Ledger',
        sleep: Callable = time.sleep,
    ):
        self.spreadsheet_id = spreadsheet_id
        self.http = http
        self.token_provider = token_provider
        self.sheet_name = sheet_name
        self.sleep = sleep
        self.base_url = 'https://sheets.googleapis.com/v4/spreadsheets'

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.token_provider()}',
            'Content-Type': 'application/json',
        }

    def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        response = self.http.request(method, url, **kw)
        attempt = 0
        while response.status_code in _RETRYABLE and attempt < 3:
            attempt += 1
            self.sleep(0.5 * (2 ** (attempt - 1)))
            response = self.http.request(method, url, **kw)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{method} {url} -> {response.status_code}",
                request=response.request,
                response=response,
            )
        return response

    def _quote_sheet(self) -> str:
        name = self.sheet_name
        if ' ' in name or "'" in name:
            return "'" + name.replace("'", "''") + "'"
        return name

    def _range(self, rng: str) -> str:
        from urllib.parse import quote
        return quote(f"{self._quote_sheet()}!{rng}", safe=":!$")

    def ensure_header(self) -> None:
        url = (
            f"{self.base_url}/{self.spreadsheet_id}/values/"
            f"{self._range('A1:T1')}"
        )
        response = self._request('GET', url, headers=self._headers())
        data = response.json()
        values = data.get('values')
        if not values or values[0] != HEADER:
            self._update_header()

    def _update_header(self) -> None:
        url = (
            f"{self.base_url}/{self.spreadsheet_id}/values/"
            f"{self._range('A1:T1')}?valueInputOption=RAW"
        )
        self._request('PUT', url, headers=self._headers(), json={'values': [HEADER]})

    def upsert(self, rows: list[dict]) -> dict[str, int]:
        deduped: dict[str, dict] = {}
        for row in rows:
            deduped[row['txn_id']] = row
        rows = list(deduped.values())

        row_index = self._get_row_index()
        updates = [r for r in rows if r['txn_id'] in row_index]
        appends = [r for r in rows if r['txn_id'] not in row_index]

        updated = 0
        appended = 0

        for chunk in self._chunks(updates, 500):
            updated += self._batch_update(chunk, row_index)
        for chunk in self._chunks(appends, 500):
            appended += self._batch_append(chunk)

        return {'updated': updated, 'appended': appended}

    @staticmethod
    def _chunks(items: list, size: int):
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def _get_row_index(self) -> dict[str, int]:
        url = f"{self.base_url}/{self.spreadsheet_id}/values/{self._range('A:A')}"
        response = self._request('GET', url, headers=self._headers())
        data = response.json()
        index: dict[str, int] = {}
        for i, row in enumerate(data.get('values', []), start=1):
            if i == 1 or not row:
                continue
            index[row[0]] = i
        return index

    def _batch_update(self, rows: list[dict], row_index: dict[str, int]) -> int:
        url = f"{self.base_url}/{self.spreadsheet_id}/values:batchUpdate"
        data = []
        for row in rows:
            n = row_index[row['txn_id']]
            data.append({
                'range': f"{self._quote_sheet()}!A{n}:T{n}",
                'values': [self._row_to_list(row)],
            })
        body = {'valueInputOption': 'RAW', 'data': data}
        self._request('POST', url, headers=self._headers(), json=body)
        return len(rows)

    def _batch_append(self, rows: list[dict]) -> int:
        url = (
            f"{self.base_url}/{self.spreadsheet_id}/values/"
            f"{self._range('A:T')}:append"
            f"?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
        )
        body = {'values': [self._row_to_list(r) for r in rows]}
        self._request('POST', url, headers=self._headers(), json=body)
        return len(rows)

    def set_status(self, txn_id: str, submit_status: str, deel_ref: str = '') -> None:
        row_index = self._get_row_index()
        if txn_id not in row_index:
            raise KeyError(f"txn_id {txn_id} not found in sheet")
        n = row_index[txn_id]
        url = (
            f"{self.base_url}/{self.spreadsheet_id}/values/"
            f"{self._range(f'S{n}')}?valueInputOption=RAW"
        )
        self._request('PUT', url, headers=self._headers(), json={'values': [[submit_status]]})
        url = (
            f"{self.base_url}/{self.spreadsheet_id}/values/"
            f"{self._range(f'T{n}')}?valueInputOption=RAW"
        )
        self._request('PUT', url, headers=self._headers(), json={'values': [[deel_ref]]})

    def _row_to_list(self, row: dict) -> list[Any]:
        return [row.get(key, '') for key in HEADER]


def row_for(
    txn: Transaction,
    result: PolicyResult,
    trip_id: str,
    city: str | None,
    country: str | None,
    screenshot_url: str,
    ocr_ok: bool,
) -> dict:
    return {
        "txn_id": txn.txn_id,
        "approved_at": txn.approved_at.isoformat(),
        "merchant": txn.merchant,
        "amount": str(txn.amount),
        "currency": txn.currency,
        "amount_krw": str(txn.amount_krw) if txn.amount_krw is not None else '',
        "card_last4": txn.card_last4,
        "category": result.category,
        "trip_id": trip_id,
        "city": city or '',
        "country": country or '',
        "screenshot_url": screenshot_url,
        "ocr_ok": str(ocr_ok),
        "policy_status": result.status,
        "policy_reason": '; '.join(result.reasons),
        "policy_cap": str(result.cap) if result.cap is not None else '',
        "reimbursable": str(result.reimbursable),
        "submit_status": '',
        "deel_ref": '',
        "notes": '',
    }
