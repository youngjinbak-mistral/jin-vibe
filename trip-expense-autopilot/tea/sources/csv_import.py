from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tea.models import Transaction

SEOUL = ZoneInfo("Asia/Seoul")

COLUMNS = {
    "이용일자": "date",
    "이용시간": "time",
    "가맹점명": "merchant",
    "이용금액": "amount",
    "통화": "currency",
    "원화금액": "amount_krw",
    "승인번호": "approval_no",
    "카드번호": "card_no",
    "취소여부": "status",
    "국가": "country",
}

_CANCEL_MAP = {
    "": "approved",
    "취소": "cancelled",
    "부분취소": "partial_cancel",
}


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    s = str(value).replace(",", "").strip()
    if not s:
        return None
    return Decimal(s)


def _last4(card_no: str | None) -> str:
    digits = "".join(ch for ch in str(card_no or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def load_csv(path: str | Path) -> list[Transaction]:
    p = Path(path)
    text = _read_text(p)
    reader = csv.DictReader(text.splitlines())
    txns: list[Transaction] = []
    for raw_row in reader:
        row: dict[str, str | None] = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            mapped = COLUMNS.get(key.strip())
            if mapped:
                row[mapped] = value.strip() if isinstance(value, str) else value

        date_s = (row.get("date") or "").strip().replace("-", "").replace("/", "")
        time_s = (row.get("time") or "000000").strip().replace(":", "").zfill(6)
        if not date_s:
            continue
        if len(date_s) == 8:
            dt = datetime.strptime(date_s + time_s, "%Y%m%d%H%M%S")
        else:
            dt = datetime.strptime(date_s + time_s, "%y%m%d%H%M%S")
        approved_at = dt.replace(tzinfo=SEOUL)

        merchant = (row.get("merchant") or "").strip()
        currency = (row.get("currency") or "KRW").strip().upper()
        amount = _to_decimal(row.get("amount")) or Decimal("0")
        status = _CANCEL_MAP.get((row.get("status") or "").strip(), "approved")
        if status == "cancelled":
            amount = -abs(amount)
        amount_krw = _to_decimal(row.get("amount_krw"))
        card_last4 = _last4(row.get("card_no"))
        approval_no = (row.get("approval_no") or "").strip()
        country = (row.get("country") or "").strip().upper() or None
        if len(country or "") != 2:
            country = None

        txn_id_source = (
            f"{card_last4}|{approval_no}|{approved_at.isoformat()}|{amount}|{currency}"
        )
        txn_id = hashlib.sha1(txn_id_source.encode()).hexdigest()[:16]

        txns.append(
            Transaction(
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
                mcc_category=None,
                raw={k: v for k, v in raw_row.items() if k is not None},
            )
        )
    return txns
