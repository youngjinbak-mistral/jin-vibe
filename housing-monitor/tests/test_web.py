import re

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import Complex, PriceRecord, ReviewItem
from tests.conftest import csrf_of


def new_complex(client, tok, **kw):
    data = {
        "csrf": tok, "name": "e편한세상 옥수 파크힐스", "aliases": "옥수파크힐스", "gu": "성동구", "dong": "옥수동",
        "nearest_station": "옥수역 (3호선)", "building_year": "2016", "units": "1976",
        "u59_exclusive_m2": "59.97", "u59_supply_m2": "81.2", "u84_exclusive_m2": "84.95", "u84_supply_m2": "112.3",
    }
    data.update(kw)
    return client.post("/complexes", data=data)


def test_seed_and_dashboard(client):
    html = client.get("/").text
    assert "래미안 파크스위트" in html
    assert "광진구" in html


def test_add_edit_remove_complex(client, app):
    tok = csrf_of(client, "/complexes/new")
    r = new_complex(client, tok)
    assert r.status_code == 303
    cid = int(r.headers["location"].rsplit("/", 1)[1])
    page = client.get(f"/complexes/{cid}").text
    assert "옥수역" in page and "전용 84.95㎡ / 공급 112.3㎡" in page
    r = client.post(f"/complexes/{cid}", data={"csrf": tok, "name": "e편한세상 옥수 파크힐스", "gu": "성동구", "hill_note": "언덕 있음", "u84_exclusive_m2": "84.95"})
    assert r.status_code == 303
    assert "언덕 있음" in client.get(f"/complexes/{cid}").text
    r = client.post(f"/complexes/{cid}/remove", data={"csrf": tok})
    with app.state.SessionLocal() as db:
        assert db.get(Complex, cid) is None


def test_complex_rejects_supply_as_exclusive(client):
    tok = csrf_of(client, "/complexes/new")
    new_complex(client, tok, u84_exclusive_m2="112.3")
    assert "범위를 벗어났습니다" in client.get("/complexes/new").text


def test_remove_complex_with_records_only_hides(client, app):
    tok = csrf_of(client, "/import")
    client.post("/import/confirm", data={
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "JEONSE", "nature": "ASKING",
        "deposit": "9억 5,000", "source_name": "Naver 부동산",
    })
    client.post("/complexes/1/remove", data={"csrf": tok})
    with app.state.SessionLocal() as db:
        cx = db.get(Complex, 1)
        assert cx is not None and cx.active is False
        assert db.scalars(select(PriceRecord)).first() is not None


def test_paste_parse_shows_confirmation_without_saving(client, app):
    tok = csrf_of(client, "/import")
    text = "래미안파크스위트 103동\n전세 9억 5,000\n112/84.98㎡, 12/23층\n확인 25.03.14.\nhttps://new.land.naver.com/complexes/1?articleNo=2512345678"
    html = client.post("/import/parse", data={"csrf": tok, "text": text}).text
    assert 'value="JEONSE" selected' in html
    assert 'value="84" selected' in html
    assert 'value="9억 5,000만"' in html
    assert 'value="2025-03-14"' in html
    assert "2512345678" in html
    with app.state.SessionLocal() as db:
        assert db.scalars(select(PriceRecord)).first() is None


def test_confirm_requires_checkbox(client, app):
    tok = csrf_of(client, "/import")
    client.post("/import/confirm", data={"csrf": tok, "complex_id": "1", "size_class": "84", "tx_type": "SALE", "nature": "ASKING", "price": "20억", "source_name": "x"})
    with app.state.SessionLocal() as db:
        assert db.scalars(select(PriceRecord)).first() is None


def test_sale_form_ignores_deposit_field(client, app):
    tok = csrf_of(client, "/import")
    r = client.post("/import/confirm", data={
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "SALE", "nature": "ASKING",
        "price": "21억", "deposit": "9억", "monthly_rent_man": "100", "source_name": "Naver 부동산",
    })
    assert r.status_code == 303
    with app.state.SessionLocal() as db:
        rec = db.scalars(select(PriceRecord)).one()
        assert (rec.price_krw, rec.deposit_krw, rec.monthly_rent_krw) == (2_100_000_000, None, None)


def test_wolse_form_requires_both(client, app):
    tok = csrf_of(client, "/import")
    client.post("/import/confirm", data={
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "59", "tx_type": "WOLSE", "nature": "ASKING",
        "deposit": "1억", "source_name": "Naver 부동산",
    })
    assert "보증금과 월세" in client.get("/import").text
    client.post("/import/confirm", data={
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "59", "tx_type": "WOLSE", "nature": "ASKING",
        "deposit": "1억", "monthly_rent_man": "250", "source_name": "Naver 부동산",
    })
    with app.state.SessionLocal() as db:
        rec = db.scalars(select(PriceRecord)).one()
        assert (rec.deposit_krw, rec.monthly_rent_krw) == (100_000_000, 2_500_000)


def test_ambiguous_goes_to_review_and_resolves(client, app):
    tok = csrf_of(client, "/import")
    base = {
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "SALE", "nature": "ACTUAL",
        "price": "20억 9,800", "floor": "12", "contract_date": "2026-09-03", "source_name": "국토교통부 실거래가",
    }
    client.post("/import/confirm", data=base)
    r = client.post("/import/confirm", data={**base, "contract_date": "2026-09-21"})
    assert r.headers["location"].startswith("/review/")
    rid = r.headers["location"].rsplit("/", 1)[1]
    assert "검토 필요" in client.get("/review").text
    client.post(f"/review/{rid}", data={"csrf": tok, "action": "separate"})
    with app.state.SessionLocal() as db:
        assert len(db.scalars(select(PriceRecord)).all()) == 2
        assert db.get(ReviewItem, int(rid)).status == "SEPARATE"


def test_series_api_filters_and_separates(client):
    tok = csrf_of(client, "/import")
    common = {"csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "source_name": "x"}
    client.post("/import/confirm", data={**common, "tx_type": "SALE", "nature": "ACTUAL", "price": "20억", "contract_date": "2026-01-02"})
    client.post("/import/confirm", data={**common, "tx_type": "JEONSE", "nature": "ASKING", "deposit": "9억", "report_date": "2026-02-02"})
    client.post("/import/confirm", data={**common, "tx_type": "WOLSE", "nature": "ASKING", "deposit": "1억", "monthly_rent_man": "250", "report_date": "2026-02-03", "is_estimate": "on"})
    j = client.get("/api/complexes/1/series", params={"tx_type": "SALE"}).json()
    assert [p["price_krw"] for s in j["series"] for p in s["points"]] == [2_000_000_000]
    j = client.get("/api/complexes/1/series", params={"tx_type": "JEONSE", "nature": "ACTUAL"}).json()
    assert j["series"] == []
    j = client.get("/api/complexes/1/series", params={"tx_type": "WOLSE"}).json()
    pt = j["series"][0]["points"][0]
    assert (pt["deposit_krw"], pt["monthly_rent_krw"], pt["price_krw"], pt["is_estimate"]) == (100_000_000, 2_500_000, None, True)
    assert client.get("/api/complexes/1/series", params={"tx_type": "X"}).status_code == 400
    assert client.get("/api/complexes/999/series").status_code == 404


def test_estimate_label_rendered(client):
    tok = csrf_of(client, "/import")
    r = client.post("/import/confirm", data={
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "SALE", "nature": "ASKING",
        "price": "20억", "source_name": "x", "is_estimate": "on", "estimate_note": "규칙 기반",
    })
    page = client.get(r.headers["location"]).text
    assert "추정" in page and "규칙 기반" in page
    assert "추정" in client.get("/").text


def test_csrf_required(client, app):
    r = client.post("/complexes/1/remove", data={"csrf": "bad"})
    assert r.status_code == 400
    with app.state.SessionLocal() as db:
        assert db.get(Complex, 1).active


def test_secret_never_rendered_or_logged(client, caplog):
    tok = csrf_of(client)
    with caplog.at_level("DEBUG"):
        client.post("/settings/secrets", data={"csrf": tok, "name": "molit_service_key", "value": "SERVICE-KEY-XYZ"})
        html = client.get("/settings").text
    assert "SERVICE-KEY-XYZ" not in html
    assert "암호화 저장됨" in html
    assert "SERVICE-KEY-XYZ" not in caplog.text


def test_secret_name_whitelist(client):
    tok = csrf_of(client)
    assert client.post("/settings/secrets", data={"csrf": tok, "name": "google_refresh_token", "value": "x"}).status_code == 400
    assert client.post("/settings/secrets", data={"csrf": tok, "name": "other", "value": "x"}).status_code == 400


def test_app_password_gate(tmp_path, google):
    app = create_app(
        database_url=f"sqlite:///{tmp_path}/p.db", master_key=Fernet.generate_key().decode(),
        http_client=google.client(), session_secret="s", app_password="pw-123", public_base_url="http://testserver",
    )
    with TestClient(app, follow_redirects=False) as c:
        assert c.get("/").headers["location"] == "/login"
        assert c.get("/api/complexes/1/series").status_code == 401
        tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
        c.post("/login", data={"csrf": tok, "password": "wrong"})
        assert c.get("/").status_code == 303
        c.post("/login", data={"csrf": tok, "password": "pw-123"})
        assert c.get("/").status_code == 200


def test_missing_master_key_fails_closed(tmp_path, google):
    import pytest

    from app.secrets_store import SecretStoreError

    with pytest.raises(SecretStoreError):
        create_app(database_url=f"sqlite:///{tmp_path}/m.db", master_key="", http_client=google.client())


def test_settings_general_saves(client):
    tok = csrf_of(client)
    client.post("/settings/general", data={
        "csrf": tok, "fresh_actual": "30", "fresh_asking": "7", "commute_1": "판교", "commute_2": "수원", "commute_3": "여의도",
        "anchor_name": "파크빌", "anchor_enrollment": "2027-03", "watch_areas": "광진구: 광장동, 구의동\n성동구: 옥수동",
    })
    html = client.get("/settings").text
    assert 'value="30"' in html and "여의도" in html


def test_non_finite_area_rejected(client, app):
    tok = csrf_of(client, "/import")
    client.post("/import/confirm", data={
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "SALE", "nature": "ASKING",
        "price": "20억", "exclusive_m2": "nan", "source_name": "x",
    })
    with app.state.SessionLocal() as db:
        assert db.scalars(select(PriceRecord)).first() is None


def test_unknown_review_action_400(client):
    tok = csrf_of(client, "/import")
    assert client.post("/review/1", data={"csrf": tok, "action": "merge"}).status_code == 400


def test_preview_required_examples_prefill_exact_amounts(client):
    tok = csrf_of(client, "/import")
    cases = [
        ("전세 8억 84㎡", 'name="deposit" value="8억"'),
        ("매매 84㎡ 12억", 'name="price" value="12억"'),
        ("전세 84㎡ 보증금 8억", 'name="deposit" value="8억"'),
        ("전세 15층 8억", 'name="deposit" value="8억"'),
        ("매매 12억 5,000", 'name="price" value="12억 5,000만"'),
    ]
    for text, needle in cases:
        html = client.post("/import/parse", data={"csrf": tok, "text": text}).text
        assert needle in html, text


def test_preview_ambiguous_amount_is_flagged_and_left_blank(client, app):
    tok = csrf_of(client, "/import")
    html = client.post("/import/parse", data={"csrf": tok, "text": "매매 12억 5 84㎡"}).text
    assert "확정할 수 없습니다" in html
    assert 'name="price" value=""' in html
    with app.state.SessionLocal() as db:
        assert db.scalars(select(PriceRecord)).first() is None


def test_confirm_rejects_ambiguous_or_polluted_amount(client, app):
    tok = csrf_of(client, "/import")
    for bad in ("12억 84㎡", "12억 5", "1,200,000,000", "12억 15층", "12억 13억"):
        client.post("/import/confirm", data={
            "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "SALE",
            "nature": "ASKING", "price": bad, "source_name": "x",
        })
        assert "저장하지 않았습니다" in client.get("/import").text, bad
    with app.state.SessionLocal() as db:
        assert db.scalars(select(PriceRecord)).first() is None


def test_confirm_saves_exact_krw(client, app):
    tok = csrf_of(client, "/import")
    client.post("/import/confirm", data={
        "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "SALE",
        "nature": "ASKING", "price": "12억 5,000", "source_name": "x",
    })
    with app.state.SessionLocal() as db:
        assert db.scalars(select(PriceRecord)).one().price_krw == 1_250_000_000
