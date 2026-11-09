import threading
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import google_oauth
from .models import Complex, PriceRecord, SheetAppend, SheetConnection, utcnow
from .secrets_store import SecretStore
from .sheets import (
    ID_HEADER,
    VERSION_HEADER,
    DestinationMismatch,
    SheetsClient,
    SheetsError,
    build_row,
    observation_values,
    parse_spreadsheet_id,
    plan_columns,
)

PROPOSED_TAB = "관측기록(앱)"
APPEND_BATCH = 200
_SYNC_LOCK = threading.Lock()


class SetupRequired(RuntimeError):
    pass


class TokenProvider:
    def __init__(self, store: SecretStore, http: httpx.Client):
        self.store = store
        self.http = http
        self._cache: google_oauth.TokenBundle | None = None

    def client_config(self, db: Session) -> tuple[str, str]:
        cid = self.store.get(db, "google_client_id")
        csec = self.store.get(db, "google_client_secret")
        if not cid or not csec:
            raise SetupRequired("설정에서 Google OAuth 클라이언트 ID/시크릿을 먼저 입력하세요.")
        return cid, csec

    def is_connected(self, db: Session) -> bool:
        return self.store.get(db, "google_refresh_token") is not None

    def save_initial(self, db: Session, bundle: google_oauth.TokenBundle) -> None:
        self.store.set(db, "google_refresh_token", bundle.refresh_token)
        self._cache = bundle

    def access_token(self, db: Session) -> str:
        if self._cache and self._cache.expires_at > time.time():
            return self._cache.access_token
        rt = self.store.get(db, "google_refresh_token")
        if not rt:
            raise google_oauth.ReconnectRequired("Google 계정이 연결되어 있지 않습니다. 설정에서 한 번 연결해 주세요.")
        cid, csec = self.client_config(db)
        try:
            bundle = google_oauth.refresh(self.http, cid, csec, rt)
        except google_oauth.ReconnectRequired:
            self.store.delete(db, "google_refresh_token")
            db.commit()
            self._cache = None
            raise
        if bundle.refresh_token and bundle.refresh_token != rt:
            self.store.set(db, "google_refresh_token", bundle.refresh_token)
            db.commit()
        self._cache = bundle
        return bundle.access_token

    def account_email(self, db: Session) -> str | None:
        return google_oauth.fetch_email(self.http, self.access_token(db))

    def disconnect(self, db: Session) -> None:
        rt = self.store.get(db, "google_refresh_token")
        if rt:
            try:
                google_oauth.revoke(self.http, rt)
            except httpx.HTTPError:
                pass
        self.store.delete(db, "google_refresh_token")
        self._cache = None


def active_connection(db: Session) -> SheetConnection | None:
    return db.scalars(
        select(SheetConnection).where(SheetConnection.state != "ABANDONED").order_by(SheetConnection.id.desc())
    ).first()


def start_connection(db: Session, tokens: TokenProvider, url: str) -> SheetConnection:
    sid = parse_spreadsheet_id(url)
    if not sid:
        raise SheetsError("Google Sheets 워크북 URL 형식이 아닙니다 (https://docs.google.com/spreadsheets/d/... 형식).")
    email = tokens.account_email(db)
    if not email:
        raise SheetsError("연결된 Google 계정 이메일을 확인할 수 없어 중단합니다. 다시 연결해 주세요.")
    meta = SheetsClient(tokens.http, tokens.access_token(db)).metadata(sid)
    if meta.spreadsheet_id != sid:
        raise DestinationMismatch("요청한 워크북과 Google이 반환한 워크북 ID가 다릅니다. 중단합니다.")
    for old in db.scalars(select(SheetConnection).where(SheetConnection.state != "ABANDONED")):
        old.state = "ABANDONED"
    conn = SheetConnection(
        spreadsheet_id=sid,
        spreadsheet_url=url.strip(),
        title=meta.title,
        account_email=email,
        state="PENDING_CONFIRMATION",
        tabs_snapshot=meta.tabs,
    )
    db.add(conn)
    db.flush()
    return conn


def confirm_destination(db: Session, conn: SheetConnection, email_typed: str, title_typed: str) -> None:
    if conn.state != "PENDING_CONFIRMATION":
        raise SheetsError("확인 대기 중인 연결이 아닙니다.")
    if email_typed.strip().lower() != conn.account_email.lower() or title_typed.strip() != conn.title:
        raise DestinationMismatch("입력한 계정/워크북 제목이 표시된 값과 다릅니다. 의도한 워크북이 아니면 연결을 취소하세요.")
    conn.state = "CONFIRMED"
    conn.confirmed_at = utcnow()


def _verify_live(db: Session, tokens: TokenProvider, conn: SheetConnection) -> tuple[SheetsClient, dict]:
    if conn.confirmed_at is None:
        raise SetupRequired("워크북 확인이 끝나지 않았습니다.")
    email = tokens.account_email(db)
    if not email or email.lower() != conn.account_email.lower():
        raise DestinationMismatch(
            f"현재 연결된 Google 계정({email or '알 수 없음'})이 확인한 계정({conn.account_email})과 다릅니다. 쓰기를 중단했습니다."
        )
    client = SheetsClient(tokens.http, tokens.access_token(db))
    meta = client.metadata(conn.spreadsheet_id)
    if meta.spreadsheet_id != conn.spreadsheet_id or meta.title != conn.title:
        raise DestinationMismatch(
            f"워크북 제목이 확인 당시('{conn.title}')와 다릅니다(현재 '{meta.title}'). 쓰기를 중단했습니다. 다시 확인해 주세요."
        )
    tabs = {t["title"]: t for t in meta.tabs}
    return client, tabs


def read_tab_structure(db: Session, tokens: TokenProvider, conn: SheetConnection, tab: str, header_row: int) -> dict:
    client, tabs = _verify_live(db, tokens, conn)
    if tab not in tabs:
        raise SheetsError(f"'{tab}' 탭을 찾을 수 없습니다.")
    rows = client.read_rows(conn.spreadsheet_id, tab, header_row, header_row)
    headers = rows[0] if rows else []
    plan = plan_columns(headers)
    conn.target_tab = tab
    _assert_columns_empty(client, conn, plan, header_row)
    conn.target_sheet_gid = tabs[tab]["sheet_id"]
    conn.header_row = header_row
    conn.existing_headers = headers
    conn.column_plan = plan
    conn.state = "PLAN_PENDING"
    conn.plan_approved_at = None
    return plan


def propose_new_tab_plan() -> dict:
    return plan_columns([])


def approve_new_tab(db: Session, tokens: TokenProvider, conn: SheetConnection, title: str = PROPOSED_TAB) -> None:
    client, tabs = _verify_live(db, tokens, conn)
    if title in tabs:
        raise SheetsError(f"'{title}' 탭이 이미 있습니다. 기존 탭을 선택하세요.")
    gid = client.add_tab(conn.spreadsheet_id, title)
    conn.target_tab = title
    conn.target_sheet_gid = gid
    conn.header_row = 1
    conn.existing_headers = []
    conn.column_plan = plan_columns([])
    conn.state = "PLAN_PENDING"
    conn.plan_approved_at = None


def _assert_columns_empty(client: SheetsClient, conn: SheetConnection, plan: dict, header_row: int) -> None:
    if not plan["new_columns"]:
        return
    cols = [c["col"] for c in plan["new_columns"]]
    existing = client.read_columns(conn.spreadsheet_id, conn.target_tab, cols, header_row)
    occupied = [
        plan["new_columns"][i]["letter"]
        for i, vals in enumerate(existing)
        if any(str(v).strip() for v in vals)
    ]
    if occupied:
        raise SheetsError(
            f"새 관측 열을 추가할 위치({', '.join(occupied)}열)에 기존 데이터가 있습니다. 덮어쓰지 않도록 중단합니다."
        )


def approve_plan(db: Session, tokens: TokenProvider, conn: SheetConnection) -> None:
    if conn.state != "PLAN_PENDING" or not conn.column_plan:
        raise SheetsError("승인할 열 배치안이 없습니다.")
    with _SYNC_LOCK:
        client, tabs = _verify_live(db, tokens, conn)
        _check_tab_unchanged(client, conn, tabs, allow_new_headers_missing=True)
        _assert_columns_empty(client, conn, conn.column_plan, conn.header_row)
        if conn.column_plan["new_columns"]:
            grid = tabs[conn.target_tab]
            client.ensure_grid(
                conn.spreadsheet_id, conn.target_sheet_gid, None, 0, grid.get("cols"), conn.column_plan["width"]
            )
            client.write_header_cells(conn.spreadsheet_id, conn.target_tab, conn.header_row, conn.column_plan["new_columns"])
        conn.state = "READY"
        conn.plan_approved_at = utcnow()


def _trim(headers: list) -> list[str]:
    out = [str(h) if h is not None else "" for h in headers]
    while out and not out[-1].strip():
        out.pop()
    return out


def _check_tab_unchanged(client: SheetsClient, conn: SheetConnection, tabs: dict, allow_new_headers_missing=False) -> None:
    tab = tabs.get(conn.target_tab)
    if tab is None or tab["sheet_id"] != conn.target_sheet_gid:
        raise DestinationMismatch(f"대상 탭 '{conn.target_tab}'이 없거나 바뀌었습니다. 쓰기를 중단했습니다.")
    rows = client.read_rows(conn.spreadsheet_id, conn.target_tab, conn.header_row, conn.header_row)
    headers = rows[0] if rows else []
    original = _trim(conn.existing_headers or [])
    current = [str(h) if h is not None else "" for h in headers]
    if [current[i] if i < len(current) else "" for i in range(len(original))] != original:
        raise DestinationMismatch("기존 머리글 행이 연결 확인 당시와 다릅니다. 열 배치를 다시 확인해 주세요. 쓰기를 중단했습니다.")
    plan = conn.column_plan
    for c in plan["new_columns"]:
        actual = current[c["col"]] if c["col"] < len(current) else ""
        if actual == c["header"]:
            continue
        if allow_new_headers_missing and actual == "":
            continue
        raise DestinationMismatch(
            f"{c['letter']}열 머리글이 예상('{c['header']}')과 다릅니다(현재 '{actual}'). 열 배치를 다시 확인해 주세요."
        )
    if len(_trim(current)) > plan["width"]:
        raise DestinationMismatch("관측 열 오른쪽에 새 머리글이 생겼습니다. 열 배치를 다시 확인해 주세요. 쓰기를 중단했습니다.")


def _canon_version(v) -> str:
    try:
        return str(int(float(str(v).strip())))
    except ValueError:
        return str(v).strip()


def _existing_keys(client: SheetsClient, conn: SheetConnection) -> set[tuple[str, str]]:
    m = conn.column_plan["mapping"]
    id_col, ver_col = m["obs_id"], m["version"]
    ids, vers = client.read_columns(conn.spreadsheet_id, conn.target_tab, [id_col, ver_col], conn.header_row + 1, unformatted=True)
    keys = set()
    for i, uid in enumerate(ids):
        if uid not in (None, ""):
            keys.add((str(uid).strip(), _canon_version(vers[i]) if i < len(vers) else ""))
    return keys


def pending_records(db: Session, conn: SheetConnection) -> list[PriceRecord]:
    done = select(SheetAppend.record_id).where(SheetAppend.connection_id == conn.id)
    return list(
        db.scalars(select(PriceRecord).where(PriceRecord.id.not_in(done)).order_by(PriceRecord.created_at, PriceRecord.id))
    )


def sync(db: Session, tokens: TokenProvider, conn: SheetConnection | None) -> dict:
    if conn is None or conn.state != "READY":
        raise SetupRequired("Google Sheet 연결과 열 배치 승인이 끝나야 동기화할 수 있습니다.")
    if not _SYNC_LOCK.acquire(timeout=60):
        raise SheetsError("다른 동기화가 진행 중입니다. 잠시 후 다시 시도하세요.")
    try:
        client, tabs = _verify_live(db, tokens, conn)
        _check_tab_unchanged(client, conn, tabs)
        todo = pending_records(db, conn)
        if not todo:
            conn.last_error = ""
            conn.last_sync_at = utcnow()
            db.commit()
            return {"appended": 0, "already_present": 0}
        present = _existing_keys(client, conn)
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        complexes = {c.id: c for c in db.scalars(select(Complex))}
        to_append: list[tuple[PriceRecord, list]] = []
        already = 0
        for rec in todo:
            if (rec.record_uid, str(rec.version)) in present:
                db.add(SheetAppend(connection_id=conn.id, record_id=rec.id, record_uid=rec.record_uid, version=rec.version, updated_range="(이미 시트에 있음)"))
                already += 1
                continue
            vals = observation_values(rec, complexes[rec.complex_id], now)
            to_append.append((rec, build_row(vals, conn.column_plan["mapping"], conn.column_plan["width"])))
        db.commit()
        appended = 0
        for i in range(0, len(to_append), APPEND_BATCH):
            chunk = to_append[i : i + APPEND_BATCH]
            if i:
                client, tabs = _verify_live(db, tokens, conn)
                _check_tab_unchanged(client, conn, tabs)
            last = max(client.last_used_row(conn.spreadsheet_id, conn.target_tab), conn.header_row)
            grid = tabs[conn.target_tab]
            client.ensure_grid(
                conn.spreadsheet_id, conn.target_sheet_gid, grid.get("rows"), last + len(chunk), grid.get("cols"), conn.column_plan["width"]
            )
            rng = client.append_rows(conn.spreadsheet_id, conn.target_tab, last, conn.column_plan["width"], [r for _, r in chunk])
            for rec, _ in chunk:
                db.add(SheetAppend(connection_id=conn.id, record_id=rec.id, record_uid=rec.record_uid, version=rec.version, updated_range=rng))
            db.commit()
            appended += len(chunk)
        conn.last_error = ""
        conn.last_sync_at = utcnow()
        db.commit()
        return {"appended": appended, "already_present": already}
    except (SheetsError, SetupRequired, google_oauth.OAuthError, httpx.HTTPError) as exc:
        db.rollback()
        conn.last_error = str(exc) if not isinstance(exc, httpx.HTTPError) else "Google에 연결할 수 없습니다."
        db.commit()
        raise
    finally:
        _SYNC_LOCK.release()


__all__ = [
    "ID_HEADER",
    "VERSION_HEADER",
    "PROPOSED_TAB",
    "TokenProvider",
    "SetupRequired",
    "active_connection",
    "start_connection",
    "confirm_destination",
    "read_tab_structure",
    "propose_new_tab_plan",
    "approve_new_tab",
    "approve_plan",
    "pending_records",
    "sync",
]
