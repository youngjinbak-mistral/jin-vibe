import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .models import NATURE_LABELS, STATUS_LABELS, TX_LABELS, Complex, PriceRecord
from .money import format_krw

API = "https://sheets.googleapis.com/v4/spreadsheets"

ID_HEADER = "관측ID"
VERSION_HEADER = "버전"

OBSERVATION_FIELDS: list[tuple[str, str, tuple[str, ...]]] = [
    ("obs_id", ID_HEADER, ()),
    ("version", VERSION_HEADER, ()),
    ("synced_at", "앱기록시각", ()),
    ("complex", "단지명", ("단지", "아파트", "아파트명", "단지 이름")),
    ("district", "구/동", ("지역", "위치")),
    ("size_class", "평형구분", ()),
    ("exclusive_m2", "전용면적(㎡)", ()),
    ("supply_m2", "공급면적(㎡)", ()),
    ("tx_type", "거래유형", ()),
    ("nature", "자료성격", ()),
    ("price_krw", "매매가(원)", ()),
    ("deposit_krw", "보증금(원)", ()),
    ("monthly_rent_krw", "월세(원)", ()),
    ("amount_display", "금액표시", ()),
    ("floor", "층", ()),
    ("contract_date", "계약일", ()),
    ("report_date", "신고·확인일", ()),
    ("status", "상태", ()),
    ("estimate", "추정여부", ()),
    ("source_name", "출처", ()),
    ("source_url", "출처URL", ()),
    ("change_reason", "변경사유", ()),
]


class SheetsError(RuntimeError):
    pass


class DestinationMismatch(SheetsError):
    pass


def parse_spreadsheet_id(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]{20,})", url.strip())
    return m.group(1) if m else None


def a1_tab(tab: str) -> str:
    return "'" + tab.replace("'", "''") + "'"


def col_letter(idx: int) -> str:
    s = ""
    n = idx + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _norm_header(h: str) -> str:
    return re.sub(r"[\s_]+", "", str(h or "")).lower()


def plan_columns(existing_headers: list[str]) -> dict:
    headers = [str(h) if h is not None else "" for h in existing_headers]
    while headers and not headers[-1].strip():
        headers.pop()
    index: dict[str, int] = {}
    for i, h in enumerate(headers):
        n = _norm_header(h)
        if n and n not in index:
            index[n] = i
    mapping: dict[str, int] = {}
    new_columns: list[dict] = []
    reused: list[dict] = []
    next_col = len(headers)
    for key, header, synonyms in OBSERVATION_FIELDS:
        found = None
        for cand in (header, *synonyms):
            i = index.get(_norm_header(cand))
            if i is not None and i not in mapping.values():
                found = i
                break
        if found is not None:
            mapping[key] = found
            reused.append({"key": key, "header": headers[found], "col": found, "letter": col_letter(found)})
        else:
            mapping[key] = next_col
            new_columns.append({"key": key, "header": header, "col": next_col, "letter": col_letter(next_col)})
            next_col += 1
    return {
        "existing_width": len(headers),
        "width": max(next_col, len(headers)),
        "mapping": mapping,
        "new_columns": new_columns,
        "reused_columns": reused,
    }


@dataclass
class SheetMeta:
    spreadsheet_id: str
    title: str
    tabs: list[dict]


class SheetsClient:
    def __init__(self, http: httpx.Client, access_token: str):
        self.http = http
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def _check(self, r: httpx.Response, what: str) -> dict:
        if r.status_code == 404:
            raise SheetsError(f"{what}: 워크북을 찾을 수 없습니다 (URL 또는 접근 권한 확인).")
        if r.status_code == 403:
            raise SheetsError(f"{what}: 이 Google 계정에는 해당 워크북 접근 권한이 없습니다.")
        if r.status_code == 429:
            raise SheetsError(f"{what}: Google Sheets 요청 한도 초과. 잠시 후 다시 시도하세요.")
        if r.status_code >= 400:
            raise SheetsError(f"{what}: Google Sheets 오류 (HTTP {r.status_code}).")
        return r.json()

    def metadata(self, spreadsheet_id: str) -> SheetMeta:
        r = self.http.get(
            f"{API}/{spreadsheet_id}",
            params={"fields": "spreadsheetId,properties.title,sheets.properties(sheetId,title,index,gridProperties)"},
            headers=self.headers,
        )
        d = self._check(r, "워크북 정보 조회")
        tabs = [
            {
                "sheet_id": s["properties"]["sheetId"],
                "title": s["properties"]["title"],
                "index": s["properties"].get("index", 0),
                "rows": s["properties"].get("gridProperties", {}).get("rowCount"),
                "cols": s["properties"].get("gridProperties", {}).get("columnCount"),
            }
            for s in d.get("sheets", [])
        ]
        return SheetMeta(d["spreadsheetId"], d["properties"]["title"], tabs)

    def read_rows(self, spreadsheet_id: str, tab: str, first_row: int, last_row: int) -> list[list[str]]:
        rng = f"{a1_tab(tab)}!{first_row}:{last_row}"
        r = self.http.get(
            f"{API}/{spreadsheet_id}/values/{quote(rng, safe='')}",
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
            headers=self.headers,
        )
        return self._check(r, "열 구조 조회").get("values", [])

    def read_columns(self, spreadsheet_id: str, tab: str, cols: list[int], start_row: int, unformatted: bool = False) -> list[list]:
        ranges = [f"{a1_tab(tab)}!{col_letter(c)}{start_row}:{col_letter(c)}" for c in cols]
        params = [("ranges", rg) for rg in ranges] + [("majorDimension", "COLUMNS")]
        if unformatted:
            params.append(("valueRenderOption", "UNFORMATTED_VALUE"))
        r = self.http.get(
            f"{API}/{spreadsheet_id}/values:batchGet",
            params=params,
            headers=self.headers,
        )
        d = self._check(r, "기존 관측ID 조회")
        out = []
        for vr in d.get("valueRanges", []):
            vals = vr.get("values", [])
            out.append(vals[0] if vals else [])
        return out

    def write_header_cells(self, spreadsheet_id: str, tab: str, header_row: int, cells: list[dict]) -> None:
        data = [
            {"range": f"{a1_tab(tab)}!{c['letter']}{header_row}", "values": [[c["header"]]]}
            for c in cells
        ]
        r = self.http.post(
            f"{API}/{spreadsheet_id}/values:batchUpdate",
            json={"valueInputOption": "RAW", "data": data},
            headers=self.headers,
        )
        self._check(r, "새 열 머리글 추가")

    def add_tab(self, spreadsheet_id: str, title: str) -> int:
        r = self.http.post(
            f"{API}/{spreadsheet_id}:batchUpdate",
            json={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            headers=self.headers,
        )
        d = self._check(r, "새 탭 생성")
        return d["replies"][0]["addSheet"]["properties"]["sheetId"]

    def last_used_row(self, spreadsheet_id: str, tab: str) -> int:
        r = self.http.get(
            f"{API}/{spreadsheet_id}/values/{quote(a1_tab(tab), safe='')}",
            params={"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
            headers=self.headers,
        )
        d = self._check(r, "마지막 사용 행 조회")
        rng = d.get("range", "")
        values = d.get("values", [])
        m = re.search(r"!([A-Z]+)?(\d+)", rng)
        start = int(m.group(2)) if m else 1
        return start + len(values) - 1 if values else 0

    def ensure_grid(self, spreadsheet_id: str, sheet_id: int, rows_have: int | None, rows_need: int, cols_have: int | None, cols_need: int) -> None:
        reqs = []
        if rows_have is not None and rows_need > rows_have:
            reqs.append({"appendDimension": {"sheetId": sheet_id, "dimension": "ROWS", "length": rows_need - rows_have}})
        if cols_have is not None and cols_need > cols_have:
            reqs.append({"appendDimension": {"sheetId": sheet_id, "dimension": "COLUMNS", "length": cols_need - cols_have}})
        if not reqs:
            return
        r = self.http.post(f"{API}/{spreadsheet_id}:batchUpdate", json={"requests": reqs}, headers=self.headers)
        self._check(r, "시트 끝에 빈 행/열 확보")

    def append_rows(self, spreadsheet_id: str, tab: str, after_row: int, width: int, rows: list[list]) -> str:
        first = after_row + 1
        last = after_row + len(rows)
        rng = f"{a1_tab(tab)}!A{first}:{col_letter(width - 1)}{last}"
        r = self.http.put(
            f"{API}/{spreadsheet_id}/values/{quote(rng, safe='')}",
            params={"valueInputOption": "RAW", "includeValuesInResponse": "false"},
            json={"range": rng, "majorDimension": "ROWS", "values": rows},
            headers=self.headers,
        )
        d = self._check(r, "관측 행 추가")
        return d.get("updatedRange", rng)


def observation_values(rec: PriceRecord, cx: Complex, synced_at: str) -> dict:
    if rec.tx_type == "SALE":
        disp = format_krw(rec.price_krw)
    elif rec.tx_type == "JEONSE":
        disp = format_krw(rec.deposit_krw)
    else:
        disp = f"보증금 {format_krw(rec.deposit_krw)} / 월 {format_krw(rec.monthly_rent_krw)}"
    if rec.is_estimate:
        disp = "[추정] " + disp
    return {
        "obs_id": rec.record_uid,
        "version": rec.version,
        "synced_at": synced_at,
        "complex": cx.name,
        "district": " ".join(x for x in (cx.gu, cx.dong) if x),
        "size_class": f"전용 {rec.size_class}㎡",
        "exclusive_m2": rec.exclusive_m2 if rec.exclusive_m2 is not None else "",
        "supply_m2": rec.supply_m2 if rec.supply_m2 is not None else "",
        "tx_type": TX_LABELS[rec.tx_type],
        "nature": NATURE_LABELS[rec.nature],
        "price_krw": rec.price_krw if rec.price_krw is not None else "",
        "deposit_krw": rec.deposit_krw if rec.deposit_krw is not None else "",
        "monthly_rent_krw": rec.monthly_rent_krw if rec.monthly_rent_krw is not None else "",
        "amount_display": disp,
        "floor": rec.floor or "",
        "contract_date": rec.contract_date.isoformat() if rec.contract_date else "",
        "report_date": rec.report_date.isoformat() if rec.report_date else "",
        "status": STATUS_LABELS.get(rec.status, rec.status),
        "estimate": "추정" if rec.is_estimate else "",
        "source_name": rec.source_name,
        "source_url": rec.source_url or "",
        "change_reason": rec.change_reason or "",
    }


def build_row(values: dict, mapping: dict, width: int) -> list:
    row: list = [""] * width
    for key, col in mapping.items():
        row[int(col)] = values.get(key, "")
    return row
