import json
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from tea.sheets import HEADER, SheetsClient
from tea.drive import DriveUploader


class Recorder:
    def __init__(self, column_a=None, header_row=None, fail_first=0, always_status=None):
        self.requests = []
        self.column_a = column_a if column_a is not None else [["txn_id"]]
        self.header_row = header_row
        self.fail_first = fail_first
        self.always_status = always_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.always_status is not None:
            return httpx.Response(self.always_status, json={})
        if self.fail_first > 0:
            self.fail_first -= 1
            return httpx.Response(429, json={"error": "rate"})
        url = unquote(str(request.url))
        if request.method == "GET" and url.split("?")[0].endswith("!A:A"):
            return httpx.Response(200, json={"values": self.column_a})
        if request.method == "GET" and "A1:T1" in url:
            if self.header_row is None:
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"values": [self.header_row]})
        return httpx.Response(200, json={})

    def url(self, r):
        return unquote(str(r.url))

    def appends(self):
        return [r for r in self.requests if r.method == "POST" and self.url(r).split("?")[0].endswith(":append")]

    def batch_updates(self):
        return [r for r in self.requests if r.method == "POST" and "values:batchUpdate" in self.url(r)]

    def puts(self):
        return [r for r in self.requests if r.method == "PUT"]


def make_client(rec, sheet_name="Ledger", sleeps=None):
    http = httpx.Client(transport=httpx.MockTransport(rec))
    sleeps = sleeps if sleeps is not None else []
    return SheetsClient("SID", http, lambda: "tok", sheet_name=sheet_name, sleep=sleeps.append)


def body(r):
    return json.loads(r.content)


def test_upsert_updates_existing_rows_at_their_row_numbers_and_appends_new():
    rec = Recorder(column_a=[["txn_id"], ["t1"], ["x"], ["y"], ["t2"]])
    client = make_client(rec)
    result = client.upsert([
        {"txn_id": "t1", "merchant": "A"},
        {"txn_id": "t2", "merchant": "B"},
        {"txn_id": "t3", "merchant": "C"},
    ])
    updates = rec.batch_updates()
    assert len(updates) == 1
    ranges = {d["range"].split("!")[-1]: d["values"][0] for d in body(updates[0])["data"]}
    assert set(ranges) == {"A2:T2", "A5:T5"}
    assert ranges["A2:T2"][0] == "t1"
    assert ranges["A5:T5"][0] == "t2"
    appends = rec.appends()
    assert len(appends) == 1
    appended = body(appends[0])["values"]
    assert [row[0] for row in appended] == ["t3"]
    assert result == {"updated": 2, "appended": 1}


def test_rows_are_written_in_header_order_with_twenty_columns():
    rec = Recorder()
    client = make_client(rec)
    client.upsert([{"txn_id": "t9", "merchant": "Hotel", "currency": "EUR", "notes": "n"}])
    row = body(rec.appends()[0])["values"][0]
    assert len(row) == len(HEADER) == 20
    assert row[HEADER.index("merchant")] == "Hotel"
    assert row[HEADER.index("currency")] == "EUR"
    assert row[HEADER.index("notes")] == "n"


def test_requests_carry_bearer_token():
    rec = Recorder()
    client = make_client(rec)
    client.upsert([{"txn_id": "t1"}])
    assert rec.requests
    for r in rec.requests:
        assert r.headers["Authorization"] == "Bearer tok"


def test_header_row_value_txn_id_is_not_treated_as_existing_transaction():
    rec = Recorder(column_a=[["txn_id"]])
    client = make_client(rec)
    client.upsert([{"txn_id": "txn_id_real"}])
    assert rec.batch_updates() == []
    assert len(rec.appends()) == 1


def test_429_then_success_is_retried_with_fake_sleep():
    rec = Recorder(column_a=[["txn_id"], ["t1"]], fail_first=1)
    sleeps = []
    client = make_client(rec, sleeps=sleeps)
    result = client.upsert([{"txn_id": "t1"}])
    assert sleeps
    assert result["updated"] == 1
    assert len(rec.batch_updates()) == 1


def test_persistent_server_error_eventually_raises():
    rec = Recorder(always_status=503)
    sleeps = []
    client = make_client(rec, sleeps=sleeps)
    with pytest.raises(httpx.HTTPError):
        client.upsert([{"txn_id": "t1"}])
    assert len(rec.requests) > 1
    assert len(rec.requests) <= 10


def test_sheet_name_with_space_is_quoted_in_range():
    rec = Recorder()
    client = make_client(rec, sheet_name="Trip Ledger")
    client.upsert([{"txn_id": "t1"}])
    gets = [rec.url(r) for r in rec.requests if r.method == "GET"]
    assert any("'Trip Ledger'!A:A" in u for u in gets)
    assert any("'Trip Ledger'!" in rec.url(r) for r in rec.appends())


def test_sheet_name_with_space_is_quoted_in_batch_update_ranges():
    rec = Recorder(column_a=[["txn_id"], ["t1"]])
    client = make_client(rec, sheet_name="Trip Ledger")
    client.upsert([{"txn_id": "t1"}])
    data = body(rec.batch_updates()[0])["data"]
    assert data[0]["range"] == "'Trip Ledger'!A2:T2"


def test_ensure_header_rewrites_row_one_when_different():
    rec = Recorder(header_row=["wrong", "header"])
    client = make_client(rec)
    client.ensure_header()
    puts = rec.puts()
    assert len(puts) == 1
    assert "A1:T1" in rec.url(puts[0])
    assert body(puts[0])["values"] == [HEADER]


def test_ensure_header_writes_when_sheet_empty():
    rec = Recorder(header_row=None)
    client = make_client(rec)
    client.ensure_header()
    assert len(rec.puts()) == 1


def test_ensure_header_noop_when_header_matches():
    rec = Recorder(header_row=list(HEADER))
    client = make_client(rec)
    client.ensure_header()
    assert rec.puts() == []


def test_1200_new_rows_are_appended_in_three_batches_of_at_most_500():
    rec = Recorder()
    client = make_client(rec)
    rows = [{"txn_id": f"t{i}"} for i in range(1200)]
    result = client.upsert(rows)
    appends = rec.appends()
    assert len(appends) == 3
    sizes = [len(body(a)["values"]) for a in appends]
    assert all(s <= 500 for s in sizes)
    assert sum(sizes) == 1200
    assert result["appended"] == 1200


def test_many_updates_are_batched_at_most_500_per_request():
    column = [["txn_id"]] + [[f"t{i}"] for i in range(1100)]
    rec = Recorder(column_a=column)
    client = make_client(rec)
    client.upsert([{"txn_id": f"t{i}"} for i in range(1100)])
    updates = rec.batch_updates()
    assert len(updates) == 3
    assert all(len(body(u)["data"]) <= 500 for u in updates)


def test_duplicate_txn_id_in_input_produces_single_row():
    rec = Recorder()
    client = make_client(rec)
    client.upsert([
        {"txn_id": "dup", "merchant": "first"},
        {"txn_id": "dup", "merchant": "second"},
    ])
    appended = [row for a in rec.appends() for row in body(a)["values"]]
    assert len(appended) == 1
    assert appended[0][0] == "dup"


def test_rerun_same_rows_does_not_append_again():
    rec = Recorder(column_a=[["txn_id"], ["t1"], ["t2"]])
    client = make_client(rec)
    client.upsert([{"txn_id": "t1"}, {"txn_id": "t2"}])
    assert rec.appends() == []


class DriveRecorder:
    def __init__(self, files):
        self.files = files
        self.requests = []

    def __call__(self, request):
        request.read()
        self.requests.append(request)
        url = str(request.url)
        if request.method == "GET" and "/drive/v3/files" in url:
            return httpx.Response(200, json={"files": self.files})
        if request.method == "POST" and "/upload/drive/v3/files" in url:
            return httpx.Response(200, json={"id": "NEW", "webViewLink": "https://drive/NEW"})
        return httpx.Response(404, json={})


def test_drive_existing_file_found_skips_upload(tmp_path: Path):
    png = tmp_path / "abc.png"
    png.write_bytes(b"\x89PNG\r\n")
    rec = DriveRecorder([{"id": "F1", "webViewLink": "https://drive/F1"}])
    up = DriveUploader(httpx.Client(transport=httpx.MockTransport(rec)), lambda: "tok", folder_id="FOLD", sleep=lambda s: None)
    link = up.upload_png(png, "abc.png")
    assert link == "https://drive/F1"
    assert not any("/upload/" in str(r.url) for r in rec.requests)
    assert all(r.method == "GET" for r in rec.requests)


def test_drive_missing_file_is_uploaded(tmp_path: Path):
    png = tmp_path / "abc.png"
    png.write_bytes(b"\x89PNGDATA")
    rec = DriveRecorder([])
    up = DriveUploader(httpx.Client(transport=httpx.MockTransport(rec)), lambda: "tok", folder_id="FOLD", sleep=lambda s: None)
    link = up.upload_png(png, "abc.png")
    assert link == "https://drive/NEW"
    uploads = [r for r in rec.requests if "/upload/" in str(r.url)]
    assert len(uploads) == 1
    assert b"\x89PNGDATA" in uploads[0].content
