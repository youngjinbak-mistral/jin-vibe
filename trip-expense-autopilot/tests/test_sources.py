import base64
import hashlib
import json
import urllib.parse
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest

from tea.models import SourceError
from tea.sources.codef import CodefClient, normalize_codef
from tea.sources.csv_import import load_csv

SEOUL = ZoneInfo("Asia/Seoul")

ROW = {
    "resUsedDate": "20261013",
    "resUsedTime": "193000",
    "resMemberStoreName": "LE PETIT BISTRO",
    "resUsedAmount": "45.50",
    "resAccountCurrency": "EUR",
    "resCardNo": "1234-****-****-5678",
    "resApprovalNo": "87654321",
    "resCancelYN": "0",
    "resKRWAmt": "70,123",
    "resHomeForeignType": "2",
}


def _ok_body(rows):
    return {"result": {"code": "CF-00000", "message": "성공"}, "data": rows}


class Recorder:
    def __init__(self, api_responses):
        self.api_responses = list(api_responses)
        self.token_calls = 0
        self.api_calls = 0
        self.token_requests = []
        self.api_requests = []

    def __call__(self, request):
        if request.url.host == "oauth.codef.io":
            self.token_calls += 1
            self.token_requests.append(request)
            return httpx.Response(200, json={"access_token": "tok-abc", "expires_in": 604800})
        self.api_calls += 1
        self.api_requests.append(request)
        if len(self.api_responses) > 1:
            return self.api_responses.pop(0)
        return self.api_responses[0]


def _client(recorder, sleeps):
    http = httpx.Client(transport=httpx.MockTransport(recorder))
    return CodefClient("cid", "secret", http=http, sleep=lambda s: sleeps.append(s))


def test_codef_url_encoded_json_body_is_parsed():
    body = urllib.parse.quote_plus(json.dumps(_ok_body([ROW]), ensure_ascii=False))
    rec = Recorder([httpx.Response(200, text=body)])
    rows = _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert len(rows) == 1
    assert rows[0]["resApprovalNo"] == "87654321"
    assert rows[0]["resMemberStoreName"] == "LE PETIT BISTRO"


def test_codef_plain_json_body_is_parsed():
    rec = Recorder([httpx.Response(200, json=_ok_body([ROW, dict(ROW, resApprovalNo="1")]))])
    rows = _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert [r["resApprovalNo"] for r in rows] == ["87654321", "1"]


def test_codef_request_targets_hana_approval_list():
    rec = Recorder([httpx.Response(200, json=_ok_body([]))])
    _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    req = rec.api_requests[0]
    assert req.url.path == "/v1/kr/card/p/account/approval-list"
    payload = json.loads(req.content)
    assert payload["organization"] == "0313"
    assert payload["connectedId"] == "conn-1"
    assert payload["startDate"] == "20261012"
    assert payload["endDate"] == "20261018"
    assert req.headers["Authorization"] == "Bearer tok-abc"


def test_codef_token_uses_basic_auth_client_credentials():
    rec = Recorder([httpx.Response(200, json=_ok_body([]))])
    _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    treq = rec.token_requests[0]
    expected = base64.b64encode(b"cid:secret").decode()
    assert treq.headers["Authorization"] == f"Basic {expected}"
    assert "grant_type=client_credentials" in treq.content.decode()


def test_codef_non_success_code_raises_source_error_with_code():
    body = {"result": {"code": "CF-12100", "message": "invalid"}, "data": {}}
    rec = Recorder([httpx.Response(200, json=body)])
    with pytest.raises(SourceError) as ei:
        _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert ei.value.code == "CF-12100"


def test_codef_url_encoded_error_raises_source_error():
    body = urllib.parse.quote_plus(json.dumps({"result": {"code": "CF-00401", "message": "x"}, "data": {}}))
    rec = Recorder([httpx.Response(200, text=body)])
    with pytest.raises(SourceError) as ei:
        _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert ei.value.code == "CF-00401"


def test_codef_retries_429_then_succeeds_with_fake_sleep():
    sleeps = []
    rec = Recorder([httpx.Response(429), httpx.Response(200, json=_ok_body([ROW]))])
    rows = _client(rec, sleeps).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert len(rows) == 1
    assert rec.api_calls == 2
    assert any(s > 0 for s in sleeps)


def test_codef_retries_5xx_then_succeeds():
    rec = Recorder([httpx.Response(503), httpx.Response(502), httpx.Response(200, json=_ok_body([ROW]))])
    rows = _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert len(rows) == 1
    assert rec.api_calls == 3


def test_codef_persistent_429_gives_up_after_three_retries():
    rec = Recorder([httpx.Response(429)])
    with pytest.raises(Exception):
        _client(rec, []).fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert rec.api_calls == 4


def test_codef_token_fetched_once_for_two_fetches():
    rec = Recorder([httpx.Response(200, json=_ok_body([ROW]))])
    client = _client(rec, [])
    client.fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    client.fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert rec.token_calls == 1
    assert rec.api_calls == 2


def test_codef_second_request_is_throttled_to_one_per_second():
    sleeps = []
    rec = Recorder([httpx.Response(200, json=_ok_body([]))])
    client = _client(rec, sleeps)
    client.fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    client.fetch_approvals("conn-1", date(2026, 10, 12), date(2026, 10, 18))
    assert sum(sleeps) > 0


def test_normalize_cancelled_is_negative():
    t = normalize_codef(dict(ROW, resCancelYN="1"))
    assert t.status == "cancelled"
    assert t.amount == Decimal("-45.50")


def test_normalize_rejected_is_skipped():
    assert normalize_codef(dict(ROW, resCancelYN="3")) is None


def test_normalize_partial_cancel_subtracts_cancel_amount():
    row = dict(ROW, resCancelYN="2", resUsedAmount="100,000", resCancelAmount="30,000",
               resHomeForeignType="1", resAccountCurrency="KRW")
    t = normalize_codef(row)
    assert t.status == "partial_cancel"
    assert t.amount == Decimal("70000")


def test_normalize_overseas_keeps_original_currency():
    t = normalize_codef(ROW)
    assert t.currency == "EUR"
    assert t.amount == Decimal("45.50")
    assert t.amount_krw == Decimal("70123")
    assert t.status == "approved"


def test_normalize_comma_amounts():
    row = dict(ROW, resUsedAmount="1,234,000", resHomeForeignType="1", resAccountCurrency="KRW", resKRWAmt="1,234,000")
    t = normalize_codef(row)
    assert t.amount == Decimal("1234000")
    assert t.amount_krw == Decimal("1234000")


def test_normalize_masked_card_takes_last4():
    t = normalize_codef(ROW)
    assert t.card_last4 == "5678"
    assert "1234" not in t.card_last4


def test_normalize_timestamp_is_seoul_aware():
    t = normalize_codef(ROW)
    assert t.approved_at.utcoffset() == timedelta(hours=9)
    assert t.approved_at == datetime(2026, 10, 13, 19, 30, 0, tzinfo=SEOUL)


def test_normalize_missing_currency_defaults_krw():
    row = {k: v for k, v in ROW.items() if k not in ("resAccountCurrency", "resKRWAmt", "resHomeForeignType")}
    row["resUsedAmount"] = "15000"
    t = normalize_codef(row)
    assert t.currency == "KRW"
    assert t.amount == Decimal("15000")
    assert t.amount_krw is None


def test_normalize_txn_id_is_stable_sha1_of_spec_key():
    t = normalize_codef(ROW)
    key = f"5678|87654321|{t.approved_at.isoformat()}|{t.amount}|EUR"
    assert t.txn_id == hashlib.sha1(key.encode()).hexdigest()[:16]
    assert normalize_codef(dict(ROW)).txn_id == t.txn_id


HEADER = "이용일자,이용시간,가맹점명,이용금액,통화,원화금액,승인번호,카드번호,취소여부,국가"
LINES = [
    HEADER,
    '2026-10-13,19:30:00,파리 식당,45.50,EUR,"70,123",87654321,1234-****-****-5678,,FR',
    '2026-10-14,09:05:10,롯데호텔 파리,"1,200.00",EUR,"1,850,000",11112222,1234-****-****-5678,취소,FR',
]


def _write(tmp_path, name, encoding):
    p = tmp_path / name
    p.write_bytes(("\r\n".join(LINES) + "\r\n").encode(encoding))
    return p


def test_csv_cp949_and_utf8_sig_parse_identically(tmp_path):
    a = load_csv(_write(tmp_path, "a.csv", "cp949"))
    b = load_csv(_write(tmp_path, "b.csv", "utf-8-sig"))
    assert len(a) == 2
    assert a == b
    assert [t.merchant for t in a] == [t.merchant for t in b] == ["파리 식당", "롯데호텔 파리"]


def test_csv_fields_normalized(tmp_path):
    t = load_csv(_write(tmp_path, "a.csv", "cp949"))[0]
    assert t.amount == Decimal("45.50")
    assert t.currency == "EUR"
    assert t.amount_krw == Decimal("70123")
    assert t.approval_no == "87654321"
    assert t.card_last4 == "5678"
    assert t.country == "FR"
    assert t.status == "approved"
    assert t.approved_at == datetime(2026, 10, 13, 19, 30, 0, tzinfo=SEOUL)


def test_csv_cancelled_row_is_negative(tmp_path):
    t = load_csv(_write(tmp_path, "b.csv", "utf-8-sig"))[1]
    assert t.status == "cancelled"
    assert t.amount == Decimal("-1200.00")
