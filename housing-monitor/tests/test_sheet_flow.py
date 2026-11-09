import re
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.models import PriceRecord, Secret, SheetAppend
from tests.conftest import csrf_of

SHEET_URL = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit#gid=0"


def setup_google(client):
    tok = csrf_of(client)
    for name, val in (("google_client_id", "cid.apps.googleusercontent.com"), ("google_client_secret", "csecret-value")):
        r = client.post("/settings/secrets", data={"csrf": tok, "name": name, "value": val})
        assert r.status_code == 303
    r = client.post("/oauth/google/start", data={"csrf": tok})
    assert r.status_code == 303
    loc = urlparse(r.headers["location"])
    q = parse_qs(loc.query)
    assert loc.netloc == "accounts.google.com"
    assert q["scope"] == ["openid email https://www.googleapis.com/auth/spreadsheets"]
    assert q["access_type"] == ["offline"]
    assert q["code_challenge_method"] == ["S256"]
    r = client.get("/oauth/google/callback", params={"code": "c0de", "state": q["state"][0]})
    assert r.status_code == 303
    return tok


def connect_and_confirm(client, google, tok):
    r = client.post("/sheet/connect", data={"csrf": tok, "url": SHEET_URL})
    assert r.status_code == 303
    html = client.get("/settings").text
    assert google.email in html and google.title in html
    assert google.writes == []
    conn_id = re.search(r'action="/sheet/(\d+)/confirm"', html).group(1)
    r = client.post(f"/sheet/{conn_id}/confirm", data={"csrf": tok, "email": google.email, "title": google.title})
    assert r.status_code == 303
    assert google.writes == []
    return conn_id


def add_sale(client, tok, price="20억 9,800", floor="12", contract="2026-09-03", source_id=""):
    return client.post(
        "/import/confirm",
        data={
            "csrf": tok, "confirmed": "on", "complex_id": "1", "size_class": "84", "tx_type": "SALE", "nature": "ACTUAL",
            "price": price, "exclusive_m2": "84.98", "supply_m2": "112.5", "floor": floor, "contract_date": contract,
            "report_date": "2026-10-14", "source_name": "국토교통부 실거래가", "source_url": "https://rt.molit.go.kr/",
            "source_record_id": source_id, "raw_snippet": "raw",
        },
    )


def test_full_flow_appends_without_touching_user_rows(client, google, app):
    tok = setup_google(client)
    with app.state.SessionLocal() as db:
        stored = db.get(Secret, "google_refresh_token")
        assert stored is not None and b"rt-secret-value" not in stored.ciphertext
        assert b"csecret-value" not in db.get(Secret, "google_client_secret").ciphertext
    settings_html = client.get("/settings").text
    assert "rt-secret-value" not in settings_html and "csecret-value" not in settings_html

    conn_id = connect_and_confirm(client, google, tok)
    original = [list(r) for r in google.grid("후보단지")]

    r = client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    assert r.status_code == 303
    html = client.get("/settings").text
    assert "열 배치안" in html
    assert google.writes == []

    r = client.post(f"/sheet/{conn_id}/approve-plan", data={"csrf": tok})
    assert r.status_code == 303
    grid = google.grid("후보단지")
    assert grid[0][:4] == ["단지", "점수", "메모", "그룹"]
    assert "관측ID" in grid[0] and "버전" in grid[0]
    assert grid[0].index("관측ID") >= 4
    for i in range(1, len(original)):
        assert grid[i][: len(original[i])] == original[i]

    r = add_sale(client, tok, source_id="T-1")
    assert r.status_code == 303
    grid = google.grid("후보단지")
    assert len(grid) == 5
    for i in range(1, len(original)):
        assert grid[i][: len(original[i])] == original[i]
    hdr = grid[0]
    row = grid[4]
    assert row[hdr.index("단지")] == "래미안 파크스위트"
    assert row[hdr.index("매매가(원)")] == 2_098_000_000
    assert row[hdr.index("보증금(원)")] == ""
    assert row[hdr.index("거래유형")] == "매매"
    assert row[hdr.index("버전")] == 1
    assert row[hdr.index("점수")] == ""
    uid = row[hdr.index("관측ID")]

    r = add_sale(client, tok, price="20억 5,000", source_id="T-1")
    grid = google.grid("후보단지")
    assert len(grid) == 6
    assert grid[4][hdr.index("매매가(원)")] == 2_098_000_000
    assert grid[5][hdr.index("관측ID")] == uid
    assert grid[5][hdr.index("버전")] == 2
    assert "금액" not in grid[5][hdr.index("변경사유")] or grid[5][hdr.index("변경사유")]

    tok = csrf_of(client)
    client.post("/sheet/sync", data={"csrf": tok})
    assert len(google.grid("후보단지")) == 6
    assert not any("rt-secret" in str(c) or "csecret" in str(c) for row in google.grid("후보단지") for c in row)


def test_sync_does_not_duplicate_rows_already_in_sheet(client, google, app):
    tok = setup_google(client)
    conn_id = connect_and_confirm(client, google, tok)
    client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    client.post(f"/sheet/{conn_id}/approve-plan", data={"csrf": tok})
    add_sale(client, tok)
    assert len(google.grid("후보단지")) == 5
    with app.state.SessionLocal() as db:
        for a in db.scalars(select(SheetAppend)):
            db.delete(a)
        db.commit()
    client.post("/sheet/sync", data={"csrf": tok})
    assert len(google.grid("후보단지")) == 5
    with app.state.SessionLocal() as db:
        assert db.scalars(select(SheetAppend)).one().updated_range == "(이미 시트에 있음)"


def test_wrong_confirmation_blocks_writes(client, google):
    tok = setup_google(client)
    client.post("/sheet/connect", data={"csrf": tok, "url": SHEET_URL})
    html = client.get("/settings").text
    conn_id = re.search(r'action="/sheet/(\d+)/confirm"', html).group(1)
    r = client.post(f"/sheet/{conn_id}/confirm", data={"csrf": tok, "email": google.email, "title": "다른 워크북"})
    assert r.status_code == 303
    assert "계정·워크북 확인 대기" in client.get("/settings").text
    r = client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    assert "워크북 확인이 끝나지 않았습니다" in client.get("/settings").text
    add_sale(client, tok)
    assert google.writes == []


def test_bad_url_never_falls_back(client, google):
    tok = setup_google(client)
    client.post("/sheet/connect", data={"csrf": tok, "url": "https://docs.google.com/spreadsheets/d/ZZZZZZZZZZZZZZZZZZZZZZZZZZZ/edit"})
    html = client.get("/settings").text
    assert "워크북을 찾을 수 없습니다" in html
    assert "/confirm" not in html
    client.post("/sheet/connect", data={"csrf": tok, "url": "https://example.com/not-a-sheet"})
    assert "URL 형식이 아닙니다" in client.get("/settings").text
    assert google.writes == []


def test_title_change_after_confirmation_stops_writes(client, google):
    tok = setup_google(client)
    conn_id = connect_and_confirm(client, google, tok)
    client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    client.post(f"/sheet/{conn_id}/approve-plan", data={"csrf": tok})
    n = len(google.grid("후보단지"))
    google.title = "회사 예산 시트"
    add_sale(client, tok)
    assert len(google.grid("후보단지")) == n
    assert "워크북 제목이 확인 당시" in client.get("/settings").text


def test_account_change_stops_writes(client, google):
    tok = setup_google(client)
    conn_id = connect_and_confirm(client, google, tok)
    client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    client.post(f"/sheet/{conn_id}/approve-plan", data={"csrf": tok})
    n = len(google.grid("후보단지"))
    google.email = "someone-else@example.com"
    add_sale(client, tok)
    assert len(google.grid("후보단지")) == n


def test_user_header_edit_stops_writes(client, google):
    tok = setup_google(client)
    conn_id = connect_and_confirm(client, google, tok)
    client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    client.post(f"/sheet/{conn_id}/approve-plan", data={"csrf": tok})
    google.grid("후보단지")[0][1] = "내 점수"
    n = len(google.grid("후보단지"))
    add_sale(client, tok)
    assert len(google.grid("후보단지")) == n
    assert "머리글" in client.get("/settings").text


def test_occupied_target_columns_refused(client, google):
    tok = setup_google(client)
    conn_id = connect_and_confirm(client, google, tok)
    google.grid("후보단지")[3] += ["", "", "", "", "", "", "손으로 쓴 값"]
    client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    assert "기존 데이터가 있습니다" in client.get("/settings").text
    assert google.writes == []


def test_new_tab_requires_approval(client, google):
    tok = setup_google(client)
    conn_id = connect_and_confirm(client, google, tok)
    client.post(f"/sheet/{conn_id}/new-tab", data={"csrf": tok, "approve": ""})
    assert "관측기록(앱)" not in google.tabs
    client.post(f"/sheet/{conn_id}/new-tab", data={"csrf": tok, "approve": "yes"})
    assert "관측기록(앱)" in google.tabs
    assert google.grid("관측기록(앱)") == []
    client.post(f"/sheet/{conn_id}/approve-plan", data={"csrf": tok})
    assert google.grid("관측기록(앱)")[0][0] == "관측ID"
    add_sale(client, tok)
    assert len(google.grid("관측기록(앱)")) == 2
    assert google.grid("후보단지")[0] == ["단지", "점수", "메모", "그룹"]


def test_revoked_refresh_token_asks_reconnect_once(client, google, app):
    tok = setup_google(client)
    conn_id = connect_and_confirm(client, google, tok)
    client.post(f"/sheet/{conn_id}/tab", data={"csrf": tok, "tab": "후보단지", "header_row": "1"})
    client.post(f"/sheet/{conn_id}/approve-plan", data={"csrf": tok})
    app.state.tokens._cache = None
    google.refresh_ok = False
    add_sale(client, tok)
    html = client.get("/").text
    html = client.get("/settings").text
    assert "Google 계정 연결" in html
    with app.state.SessionLocal() as db:
        assert db.get(Secret, "google_refresh_token") is None
        assert db.scalars(select(PriceRecord)).first() is not None


def test_access_token_refreshes_without_login(client, google, app):
    tok = setup_google(client)
    connect_and_confirm(client, google, tok)
    issued = google.access_tokens_issued
    app.state.tokens._cache = None
    with app.state.SessionLocal() as db:
        app.state.tokens.access_token(db)
    assert google.access_tokens_issued == issued + 1


def test_oauth_state_mismatch_rejected(client, google, app):
    tok = csrf_of(client)
    client.post("/settings/secrets", data={"csrf": tok, "name": "google_client_id", "value": "cid"})
    client.post("/settings/secrets", data={"csrf": tok, "name": "google_client_secret", "value": "sec"})
    client.post("/oauth/google/start", data={"csrf": tok})
    client.get("/oauth/google/callback", params={"code": "c", "state": "forged"})
    with app.state.SessionLocal() as db:
        assert db.get(Secret, "google_refresh_token") is None


def test_missing_sheets_scope_rejected(client, google, app):
    google.granted_scope = "openid email"
    tok = csrf_of(client)
    client.post("/settings/secrets", data={"csrf": tok, "name": "google_client_id", "value": "cid"})
    client.post("/settings/secrets", data={"csrf": tok, "name": "google_client_secret", "value": "sec"})
    r = client.post("/oauth/google/start", data={"csrf": tok})
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.get("/oauth/google/callback", params={"code": "c", "state": state})
    assert "Sheets 권한" in client.get("/settings").text
    with app.state.SessionLocal() as db:
        assert db.get(Secret, "google_refresh_token") is None
