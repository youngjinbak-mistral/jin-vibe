from __future__ import annotations

import time
import urllib.parse
import json
import hashlib
import base64
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from tea.models import Transaction, SourceError

SEOUL = ZoneInfo("Asia/Seoul")
_MAX_RPS = 1.0


def _parse_amount(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    s = str(value).replace(",", "").strip()
    if not s:
        return Decimal("0")
    return Decimal(s)


def _last4(card_no: str | None) -> str:
    digits = "".join(ch for ch in str(card_no or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits


class CodefClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://api.codef.io",
        token_url: str = "https://oauth.codef.io/oauth/token",
        http: httpx.Client | None = None,
        sleep=time.sleep,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self._http = http or httpx.Client(timeout=30.0)
        self._sleep = sleep
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._last_request: float = 0.0

    def token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expiry - 60:
            return self._token
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = self._http.post(
            self.token_url,
            headers={"Authorization": f"Basic {basic}"},
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = now + int(data.get("expires_in", 3600))
        return self._token

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < _MAX_RPS:
            self._sleep(_MAX_RPS - elapsed)
        self._last_request = time.time()

    def _post(self, path: str, payload: dict) -> httpx.Response:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token()}"}
        last_exc: Exception | None = None
        for attempt in range(4):
            self._throttle()
            resp = self._http.post(url, json=payload, headers=headers)
            if resp.status_code not in (429, 500, 502, 503, 504):
                return resp
            last_exc = SourceError(
                f"HTTP_{resp.status_code}", f"HTTP {resp.status_code} from {url}"
            )
            self._sleep(2 ** attempt)
        raise last_exc or SourceError("HTTP_ERROR", "request failed")

    def fetch_approvals(
        self,
        connected_id: str,
        start: date,
        end: date,
        card_no: str | None = None,
        card_password: str | None = None,
        inquiry_type: str = "1",
        member_store_info_type: str = "1",
    ) -> list[dict]:
        payload: dict[str, Any] = {
            "organization": "0313",
            "connectedId": connected_id,
            "inquiryType": inquiry_type,
            "memberStoreInfoType": member_store_info_type,
            "startDate": start.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d"),
        }
        if card_no:
            payload["cardNo"] = card_no
        if card_password:
            payload["cardPassword"] = card_password
        resp = self._post("/v1/kr/card/p/account/approval-list", payload)
        text = resp.text
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = json.loads(urllib.parse.unquote_plus(text))
        if isinstance(data, str):
            data = json.loads(urllib.parse.unquote_plus(data))
        result = data.get("result") or {}
        code = result.get("code", "")
        if code != "CF-00000":
            raise SourceError(code, result.get("message", "CODEF error"))
        return _rows(data.get("data"))


def _rows(payload: Any) -> list[dict]:
    if payload is None or payload == "":
        return []
    if isinstance(payload, dict):
        for key in ("resApprovalList", "resList", "resCardAccountList", "resAccountTransactionList"):
            if isinstance(payload.get(key), list):
                return [r for item in payload[key] for r in _rows(item)]
        return [payload] if payload.get("resUsedDate") else []
    if isinstance(payload, list):
        return [r for item in payload for r in _rows(item)]
    return []


def normalize_codef(row: dict) -> Transaction | None:
    cancel_yn = str(row.get("resCancelYN", "0") or "0")
    if cancel_yn == "3":
        return None
    status = {"0": "approved", "1": "cancelled", "2": "partial_cancel"}.get(
        cancel_yn, "approved"
    )
    used_date = str(row.get("resUsedDate", "") or "")
    used_time = str(row.get("resUsedTime", "") or "000000").zfill(6)
    dt = datetime.strptime(used_date + used_time, "%Y%m%d%H%M%S")
    approved_at = dt.replace(tzinfo=SEOUL)

    overseas = str(row.get("resHomeForeignType", "1") or "1") == "2"
    currency = row.get("resAccountCurrency") or "KRW"
    if not overseas:
        currency = "KRW"

    amount = _parse_amount(row.get("resUsedAmount"))
    if status == "cancelled":
        amount = -abs(amount)
    elif status == "partial_cancel":
        cancel_amount = _parse_amount(row.get("resCancelAmount"))
        amount = amount - cancel_amount

    amount_krw: Decimal | None = None
    krw = row.get("resKRWAmt")
    if krw not in (None, ""):
        amount_krw = _parse_amount(krw)

    card_last4 = _last4(row.get("resCardNo"))
    approval_no = str(row.get("resApprovalNo", "") or "")
    merchant = str(row.get("resMemberStoreName", "") or "").strip()

    country: str | None = None
    if overseas:
        addr = row.get("resMemberStoreAddr") or row.get("resNation")
        if addr:
            text = str(addr).strip().upper()
            for code in ("KR", "US", "GB", "FR", "DE", "JP", "CN", "SG", "AE", "MA", "CA", "CH", "NL", "BE", "PL"):
                if code in text:
                    country = code
                    break

    txn_id_source = f"{card_last4}|{approval_no}|{approved_at.isoformat()}|{amount}|{currency}"
    txn_id = hashlib.sha1(txn_id_source.encode()).hexdigest()[:16]

    return Transaction(
        txn_id=txn_id,
        approved_at=approved_at,
        merchant=merchant,
        amount=amount,
        currency=currency,
        amount_krw=amount_krw,
        card_last4=card_last4,
        approval_no=approval_no,
        status=status,
        country=country,
        mcc_category=row.get("resMemberStoreType") or None,
        raw=dict(row),
    )
