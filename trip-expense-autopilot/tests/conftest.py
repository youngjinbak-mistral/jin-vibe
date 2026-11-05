import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tea.models import Transaction, make_txn_id
from tea.trip import Trip


def make_txn(merchant, amount, currency, when_iso, status="approved", country=None, approval_no=None, amount_krw=None):
    when = datetime.fromisoformat(when_iso)
    amt = Decimal(str(amount))
    approval = approval_no or str(abs(hash((merchant, when_iso, str(amount)))) % 10**8).zfill(8)
    return Transaction(
        txn_id=make_txn_id("5678", approval, when, amt, currency),
        approved_at=when,
        merchant=merchant,
        amount=amt,
        currency=currency,
        amount_krw=Decimal(str(amount_krw)) if amount_krw is not None else None,
        card_last4="5678",
        approval_no=approval,
        status=status,
        country=country,
    )


@pytest.fixture
def paris_trip():
    return Trip.from_dict(json.loads((ROOT / "tests" / "fixtures" / "trip_paris.json").read_text()))
