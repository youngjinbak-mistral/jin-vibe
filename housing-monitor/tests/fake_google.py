import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.sheets import col_letter


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _parse_a1(rng: str):
    tab, _, cells = rng.rpartition("!")
    if tab.startswith("'") and tab.endswith("'"):
        tab = tab[1:-1].replace("''", "'")
    if not tab:
        tab, cells = cells, ""
    if tab.startswith("'") and tab.endswith("'"):
        tab = tab[1:-1].replace("''", "'")
    return tab, cells


class FakeGoogle:
    def __init__(self, email="me@example.com", title="우리집 주택 워크북", sid="1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"):
        self.email = email
        self.sid = sid
        self.title = title
        self.tabs: dict[str, dict] = {}
        self.next_gid = 100
        self.refresh_ok = True
        self.calls: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str]] = []
        self.access_tokens_issued = 0
        self.refresh_token = "rt-secret-value"
        self.granted_scope = "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/spreadsheets"

    def add_tab(self, title, rows=None, row_count=1000, col_count=26):
        self.tabs[title] = {"gid": self.next_gid, "cells": [list(r) for r in (rows or [])], "rows": row_count, "cols": col_count}
        self.next_gid += 1
        return self.tabs[title]

    def grid(self, title):
        return self.tabs[title]["cells"]

    def _get(self, tab, r, c):
        cells = self.tabs[tab]["cells"]
        if r < len(cells) and c < len(cells[r]):
            return cells[r][c]
        return ""

    def _set(self, tab, r, c, v):
        t = self.tabs[tab]
        if r >= t["rows"] or c >= t["cols"]:
            raise ValueError("exceeds grid limits")
        cells = t["cells"]
        while len(cells) <= r:
            cells.append([])
        while len(cells[r]) <= c:
            cells[r].append("")
        cells[r][c] = v

    def _trimmed(self, tab):
        cells = [list(r) for r in self.tabs[tab]["cells"]]
        for r in cells:
            while r and r[-1] in ("", None):
                r.pop()
        while cells and not cells[-1]:
            cells.pop()
        return cells

    def _read_range(self, rng, major="ROWS"):
        tab, cells = _parse_a1(rng)
        if tab not in self.tabs:
            return None
        data = self._trimmed(tab)
        if not cells:
            return {"range": f"'{tab}'!A1:{col_letter(max((len(r) for r in data), default=1) - 1)}{max(len(data), 1)}", "values": data}
        m = re.fullmatch(r"([A-Z]*)(\d*):([A-Z]*)(\d*)", cells)
        c1, r1, c2, r2 = m.groups()
        r1 = int(r1) - 1 if r1 else 0
        r2 = int(r2) - 1 if r2 else max(len(data) - 1, r1)
        ci1 = _col_index(c1) if c1 else 0
        ci2 = _col_index(c2) if c2 else max((len(r) for r in data), default=1) - 1
        if major == "COLUMNS":
            out = []
            for c in range(ci1, ci2 + 1):
                col = [self._get(tab, r, c) for r in range(r1, r2 + 1)]
                while col and col[-1] in ("", None):
                    col.pop()
                out.append(col)
            while out and not out[-1]:
                out.pop()
            return {"range": rng, "values": out}
        rows = []
        for r in range(r1, r2 + 1):
            row = [self._get(tab, r, c) for c in range(ci1, ci2 + 1)]
            while row and row[-1] in ("", None):
                row.pop()
            rows.append(row)
        while rows and not rows[-1]:
            rows.pop()
        return {"range": rng, "values": rows}

    def _write_range(self, rng, values):
        tab, cells = _parse_a1(rng)
        m = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+)?)?", cells)
        r0 = int(m.group(2)) - 1
        c0 = _col_index(m.group(1))
        for i, row in enumerate(values):
            for j, v in enumerate(row):
                self._set(tab, r0 + i, c0 + j, v)
        self.writes.append(("values", rng))

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = unquote(url.path)
        q = parse_qs(url.query)
        self.calls.append((request.method, str(request.url)))
        if url.netloc == "oauth2.googleapis.com" and path == "/token":
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["authorization_code"]:
                self.access_tokens_issued += 1
                return httpx.Response(200, json={
                    "access_token": f"at-{self.access_tokens_issued}", "expires_in": 3600,
                    "refresh_token": self.refresh_token, "scope": self.granted_scope, "id_token": "x.e30.y",
                })
            if form.get("grant_type") == ["refresh_token"]:
                if not self.refresh_ok or form.get("refresh_token") != [self.refresh_token]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.access_tokens_issued += 1
                return httpx.Response(200, json={"access_token": f"at-{self.access_tokens_issued}", "expires_in": 3600, "scope": self.granted_scope})
        if url.netloc == "oauth2.googleapis.com" and path == "/revoke":
            return httpx.Response(200, json={})
        if url.netloc == "openidconnect.googleapis.com":
            if not request.headers.get("authorization", "").startswith("Bearer at-"):
                return httpx.Response(401, json={})
            return httpx.Response(200, json={"email": self.email})
        if url.netloc != "sheets.googleapis.com":
            return httpx.Response(404, json={})
        if not request.headers.get("authorization", "").startswith("Bearer at-"):
            return httpx.Response(401, json={})
        m = re.fullmatch(r"/v4/spreadsheets/([^/:]+)(.*)", path)
        sid, rest = m.group(1), m.group(2)
        if sid != self.sid:
            return httpx.Response(404, json={"error": {"code": 404}})
        if rest == "" and request.method == "GET":
            return httpx.Response(200, json={
                "spreadsheetId": self.sid,
                "properties": {"title": self.title},
                "sheets": [
                    {"properties": {"sheetId": t["gid"], "title": name, "index": i, "gridProperties": {"rowCount": t["rows"], "columnCount": t["cols"]}}}
                    for i, (name, t) in enumerate(self.tabs.items())
                ],
            })
        if rest == ":batchUpdate":
            body = json.loads(request.content)
            replies = []
            for req in body["requests"]:
                if "addSheet" in req:
                    t = self.add_tab(req["addSheet"]["properties"]["title"])
                    self.writes.append(("addSheet", req["addSheet"]["properties"]["title"]))
                    replies.append({"addSheet": {"properties": {"sheetId": t["gid"], "title": req["addSheet"]["properties"]["title"]}}})
                elif "appendDimension" in req:
                    d = req["appendDimension"]
                    tab = next(n for n, t in self.tabs.items() if t["gid"] == d["sheetId"])
                    key = "rows" if d["dimension"] == "ROWS" else "cols"
                    self.tabs[tab][key] += d["length"]
                    self.writes.append(("appendDimension", d["dimension"]))
                    replies.append({})
                else:
                    raise AssertionError(f"unexpected batchUpdate request {req}")
            return httpx.Response(200, json={"replies": replies})
        if rest == "/values:batchGet":
            major = q.get("majorDimension", ["ROWS"])[0]
            return httpx.Response(200, json={"valueRanges": [self._read_range(r, major) for r in q.get("ranges", [])]})
        if rest == "/values:batchUpdate":
            body = json.loads(request.content)
            for d in body["data"]:
                self._write_range(d["range"], d["values"])
            return httpx.Response(200, json={})
        if rest.startswith("/values/"):
            rng = rest[len("/values/"):]
            if request.method == "GET":
                res = self._read_range(rng)
                if res is None:
                    return httpx.Response(400, json={})
                return httpx.Response(200, json=res)
            if request.method == "PUT":
                body = json.loads(request.content)
                try:
                    self._write_range(rng, body["values"])
                except ValueError:
                    return httpx.Response(400, json={"error": {"message": "exceeds grid limits"}})
                return httpx.Response(200, json={"updatedRange": rng})
            if rng.endswith(":append"):
                raise AssertionError("app must not use :append (it can insert rows and shift user data)")
        raise AssertionError(f"unhandled {request.method} {path}")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))
