from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class TeaError(Exception):
    pass


class SourceError(TeaError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class AuthRequired(TeaError):
    pass


class CaptchaRequired(TeaError):
    pass


class SelectorDrift(TeaError):
    pass


def make_txn_id(card_last4: str, approval_no: str, approved_at: datetime, amount: Decimal, currency: str) -> str:
    key = f"{card_last4}|{approval_no}|{approved_at.isoformat()}|{amount}|{currency}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Transaction:
    txn_id: str
    approved_at: datetime
    merchant: str
    amount: Decimal
    currency: str
    amount_krw: Decimal | None
    card_last4: str
    approval_no: str
    status: str
    country: str | None = None
    mcc_category: str | None = None
    raw: dict = field(default_factory=dict, compare=False, hash=False)


@dataclass
class PolicyResult:
    status: str
    category: str
    reasons: list[str]
    cap: Decimal | None
    cap_currency: str | None
    reimbursable: Decimal
