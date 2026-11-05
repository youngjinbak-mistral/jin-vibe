import base64
import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from conftest import make_txn
from tea.evidence.ocr import MistralOcrClient, ocr_check


class FakeOcr:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def ocr(self, image_bytes):
        self.calls.append(image_bytes)
        return self.text


@pytest.fixture
def png(tmp_path: Path) -> Path:
    p = tmp_path / "shot.png"
    p.write_bytes(b"\x89PNG-fake-bytes")
    return p


def test_passes_png_bytes_to_client(png):
    client = FakeOcr("LE BISTRO 45.50")
    txn = make_txn("LE BISTRO", Decimal("45.50"), "EUR", "2026-10-13T20:00:00+02:00")
    ocr_check(png, txn, client)
    assert client.calls == [b"\x89PNG-fake-bytes"]


def test_korean_won_with_thousand_separators_matches(png):
    txn = make_txn("호텔 신라", Decimal("1234000"), "KRW", "2026-10-11T12:00:00+09:00")
    res = ocr_check(png, txn, FakeOcr("호텔 신라\n승인금액 1,234,000원"))
    assert res["found_amount"] is True
    assert res["found_merchant"] is True
    assert res["ok"] is True


def test_european_decimal_comma_matches(png):
    txn = make_txn("Le Petit Bistro", Decimal("45.50"), "EUR", "2026-10-13T20:00:00+02:00")
    res = ocr_check(png, txn, FakeOcr("LE PETIT BISTRO\nTotal € 45,50\n"))
    assert res["found_amount"] is True
    assert res["ok"] is True


def test_dollar_amount_with_single_decimal_matches(png):
    txn = make_txn("Marriott Marquis", Decimal("1234.50"), "USD", "2026-10-13T20:00:00-04:00")
    res = ocr_check(png, txn, FakeOcr("MARRIOTT MARQUIS\nAmount $1,234.5\n"))
    assert res["found_amount"] is True
    assert res["ok"] is True


def test_amount_krw_matches_when_original_amount_absent(png):
    base = make_txn("Le Petit Bistro", Decimal("45.50"), "EUR", "2026-10-13T20:00:00+02:00")
    txn = dataclasses.replace(base, amount_krw=Decimal("66000"))
    res = ocr_check(png, txn, FakeOcr("LE PETIT BISTRO\n원화금액 66,000원"))
    assert res["found_amount"] is True
    assert res["ok"] is True


def test_korean_merchant_matched_with_spaces_removed(png):
    txn = make_txn("스타벅스 강남점", Decimal("5500"), "KRW", "2026-10-11T08:00:00+09:00")
    res = ocr_check(png, txn, FakeOcr("스타벅스강남점\n결제 5,500원"))
    assert res["found_merchant"] is True
    assert res["ok"] is True


def test_merchant_token_ratio_at_least_60_percent_passes(png):
    txn = make_txn("Le Petit Bistro Paris", Decimal("30"), "EUR", "2026-10-13T20:00:00+02:00")
    res = ocr_check(png, txn, FakeOcr("PETIT BISTRO PARIS\nTotal 30,00"))
    assert res["found_merchant"] is True


def test_merchant_token_ratio_below_60_percent_fails(png):
    txn = make_txn("Le Petit Bistro Paris", Decimal("30"), "EUR", "2026-10-13T20:00:00+02:00")
    res = ocr_check(png, txn, FakeOcr("BISTRO\nTotal 30,00"))
    assert res["found_merchant"] is False
    assert res["ok"] is False


def test_mismatch_returns_ok_false_with_notes(png):
    txn = make_txn("Le Petit Bistro", Decimal("45.50"), "EUR", "2026-10-13T20:00:00+02:00")
    res = ocr_check(png, txn, FakeOcr("UNRELATED SHOP\nTotal 99,99"))
    assert res["ok"] is False
    assert res["found_amount"] is False
    assert res["found_merchant"] is False
    assert res["notes"]


def test_amount_only_mismatch_is_not_ok(png):
    txn = make_txn("Le Petit Bistro", Decimal("45.50"), "EUR", "2026-10-13T20:00:00+02:00")
    res = ocr_check(png, txn, FakeOcr("LE PETIT BISTRO\nTotal 54,50"))
    assert res["found_merchant"] is True
    assert res["found_amount"] is False
    assert res["ok"] is False
    assert res["notes"]


def test_merchant_only_mismatch_is_not_ok(png):
    txn = make_txn("Le Petit Bistro", Decimal("45.50"), "EUR", "2026-10-13T20:00:00+02:00")
    res = ocr_check(png, txn, FakeOcr("CAFE DE FLORE\nTotal 45,50"))
    assert res["found_amount"] is True
    assert res["ok"] is False


def test_empty_ocr_text_is_not_ok(png):
    txn = make_txn("Le Petit Bistro", Decimal("45.50"), "EUR", "2026-10-13T20:00:00+02:00")
    res = ocr_check(png, txn, FakeOcr(""))
    assert res["ok"] is False


def test_decimal_amounts_do_not_raise_type_error(png):
    base = make_txn("Hotel Lutetia", Decimal("230.00"), "EUR", "2026-10-13T20:00:00+02:00")
    txn = dataclasses.replace(base, amount_krw=Decimal("334500.00"))
    res = ocr_check(png, txn, FakeOcr("HOTEL LUTETIA 230.00 EUR 334,500원 ref 1.2.3"))
    assert isinstance(res["ok"], bool)
    assert res["ok"] is True


def test_mistral_client_sends_data_uri_and_model():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"pages": [{"markdown": "page1"}, {"markdown": "page2"}]})

    client = MistralOcrClient("secret", httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    text = client.ocr(b"PNGDATA")
    assert "page1" in text and "page2" in text
    payload = json.loads(seen[0].content)
    assert payload["model"] == "mistral-ocr-latest"
    assert payload["document"]["type"] == "image_url"
    assert payload["document"]["image_url"] == "data:image/png;base64," + base64.b64encode(b"PNGDATA").decode()
    assert seen[0].headers["Authorization"] == "Bearer secret"


def test_mistral_client_retries_on_429():
    calls = {"n": 0}
    sleeps = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"pages": [{"markdown": "ok"}]})

    client = MistralOcrClient("k", httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    assert client.ocr(b"x") == "ok"
    assert calls["n"] == 2
    assert sleeps


def test_mistral_client_raises_on_persistent_error():
    def handler(request):
        return httpx.Response(500, json={})

    client = MistralOcrClient("k", httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(httpx.HTTPError):
        client.ocr(b"x")
