import hashlib
import hmac
import logging
import math
import os
import secrets
import time
from datetime import date, datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import google_oauth, sheet_sync
from .db import init_db, make_engine
from .defaults import DEFAULT_SETTINGS, SEED_COMPLEXES
from .listing_parser import ComplexRef, parse_listing, size_class_for
from .models import (
    NATURE_LABELS,
    SIZE_CLASSES,
    STATUS_LABELS,
    TX_LABELS,
    Complex,
    PriceRecord,
    ReviewItem,
    SheetAppend,
    SheetConnection,
    Setting,
    UnitType,
)
from .money import format_eok, format_krw, format_krw_input, parse_krw_strict, parse_manwon
from .records import (
    Candidate,
    RecordValidationError,
    ingest,
    latest_current,
    resolve_review,
    series_freshness,
    series_points,
)
from .secrets_store import KNOWN_SECRETS, SecretStore, SecretStoreError
from .sheets import SheetsError

log = logging.getLogger("housing_monitor")
BASE = Path(__file__).parent


def _auth_dependency(app_password: str | None):
    def check(request: Request):
        if not app_password:
            return
        if request.session.get("authed") is True:
            return
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    return check


class ConfigError(RuntimeError):
    pass


def _check_production_config(app_password: str | None, session_secret: str | None, base_url: str, master_key: str | None):
    problems = []
    if not master_key:
        problems.append("HM_MASTER_KEY")
    if not app_password or len(app_password) < 12:
        problems.append("HM_APP_PASSWORD (12자 이상)")
    if not session_secret or len(session_secret) < 32:
        problems.append("HM_SESSION_SECRET (32자 이상)")
    if not base_url.startswith("https://"):
        problems.append("HM_PUBLIC_BASE_URL (https://)")
    if problems:
        raise ConfigError("HM_ENV=production 에서 필수 설정이 없거나 약합니다: " + ", ".join(problems))


def create_app(
    database_url: str | None = None,
    master_key: str | None = None,
    http_client: httpx.Client | None = None,
    session_secret: str | None = None,
    app_password: str | None = None,
    public_base_url: str | None = None,
    production: bool | None = None,
) -> FastAPI:
    production = production if production is not None else os.environ.get("HM_ENV") == "production"
    if production:
        _check_production_config(
            app_password if app_password is not None else os.environ.get("HM_APP_PASSWORD"),
            session_secret or os.environ.get("HM_SESSION_SECRET"),
            (public_base_url or os.environ.get("HM_PUBLIC_BASE_URL") or ""),
            master_key if master_key is not None else os.environ.get("HM_MASTER_KEY"),
        )
    engine = make_engine(database_url)
    SessionLocal = init_db(engine)
    store = SecretStore(master_key if master_key is not None else os.environ.get("HM_MASTER_KEY"))
    http = http_client or httpx.Client(timeout=30)
    tokens = sheet_sync.TokenProvider(store, http)
    app_password = app_password if app_password is not None else os.environ.get("HM_APP_PASSWORD")
    base_url = (public_base_url or os.environ.get("HM_PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    if not session_secret:
        session_secret = os.environ.get("HM_SESSION_SECRET") or hmac.new(
            str(master_key if master_key is not None else os.environ.get("HM_MASTER_KEY", "")).encode(),
            b"housing-monitor-session",
            hashlib.sha256,
        ).hexdigest()
    if not app_password:
        log.warning("HM_APP_PASSWORD is not set: the UI has no login. Bind to 127.0.0.1 only.")

    app = FastAPI(title="서울 아파트 시세 모니터", docs_url=None, redoc_url=None, openapi_url=None)
    secure = base_url.startswith("https://")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; form-action 'self' https://accounts.google.com; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        if not request.url.path.startswith("/static/"):
            h["Cache-Control"] = "no-store"
        if secure:
            h["Strict-Transport-Security"] = "max-age=31536000"
        return response

    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        same_site="lax",
        https_only=secure,
        session_cookie="hm_session",
        max_age=60 * 60 * 24 * 14,
    )
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=BASE / "templates")
    templates.env.filters["krw"] = format_krw
    templates.env.filters["krw_input"] = format_krw_input
    templates.env.filters["eok"] = format_eok
    templates.env.globals.update(TX_LABELS=TX_LABELS, NATURE_LABELS=NATURE_LABELS, STATUS_LABELS=STATUS_LABELS)
    app.state.SessionLocal = SessionLocal
    app.state.store = store
    app.state.tokens = tokens
    app.state.engine = engine

    with SessionLocal() as db:
        for k, v in DEFAULT_SETTINGS.items():
            if db.get(Setting, k) is None:
                db.add(Setting(key=k, value=v))
        if db.scalar(select(func.count(Complex.id))) == 0 and db.get(Setting, "seeded") is None:
            for s in SEED_COMPLEXES:
                cx = Complex(**s)
                cx.unit_types = [UnitType(size_class="59"), UnitType(size_class="84")]
                db.add(cx)
            db.add(Setting(key="seeded", value=True))
        db.commit()

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    auth = _auth_dependency(app_password)

    def setting(db: Session, key: str):
        row = db.get(Setting, key)
        return row.value if row else DEFAULT_SETTINGS.get(key)

    def csrf_token(request: Request) -> str:
        tok = request.session.get("csrf")
        if not tok:
            tok = secrets.token_urlsafe(24)
            request.session["csrf"] = tok
        return tok

    def check_csrf(request: Request, token: str):
        expected = request.session.get("csrf") or ""
        if not token or not expected or not secrets.compare_digest(str(token), expected):
            raise HTTPException(status_code=400, detail="세션이 만료되었습니다. 페이지를 새로고침하세요.")

    def flash(request: Request, kind: str, msg: str):
        request.session["flashes"] = [*request.session.get("flashes", []), [kind, msg]]

    def render(request: Request, name: str, ctx: dict, status_code: int = 200):
        signed_in = request.session.get("authed") is True
        allowed = signed_in or not app_password
        pending, conn = 0, None
        if allowed:
            with SessionLocal() as db:
                pending = db.scalar(select(func.count(ReviewItem.id)).where(ReviewItem.status == "PENDING"))
                conn = sheet_sync.active_connection(db)
        flashes = request.session.pop("flashes", [])
        base = {
            "request": request,
            "authed": bool(app_password) and signed_in,
            "show_nav": allowed,
            "csrf": csrf_token(request),
            "flashes": flashes,
            "pending_reviews": pending,
            "sheet_state": conn.state if conn else None,
            "nav": ctx.pop("nav", ""),
        }
        base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status_code)

    def redirect(url: str):
        return RedirectResponse(url, status_code=303)

    def try_auto_sync(db: Session, request: Request):
        if not setting(db, "auto_sheet_sync"):
            return
        conn = sheet_sync.active_connection(db)
        if conn is None or conn.state != "READY":
            return
        try:
            res = sheet_sync.sync(db, tokens, conn)
            if res["appended"]:
                flash(request, "success", f"Google Sheet에 {res['appended']}행을 추가했습니다.")
        except google_oauth.ReconnectRequired as exc:
            flash(request, "warn", str(exc))
        except (SheetsError, sheet_sync.SetupRequired, google_oauth.OAuthError) as exc:
            flash(request, "warn", f"시트 동기화 중단: {exc}")
        except httpx.HTTPError:
            flash(request, "warn", "시트 동기화 중단: Google에 연결할 수 없습니다.")

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
            return RedirectResponse(exc.headers["Location"], status_code=303)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", {"message": exc.detail, "code": exc.status_code}, exc.status_code)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if not app_password:
            return redirect("/")
        return render(request, "login.html", {})

    failures: list[float] = []

    @app.post("/login")
    def login(request: Request, password: str = Form(...), csrf: str = Form("")):
        check_csrf(request, csrf)
        now = time.monotonic()
        failures[:] = [t for t in failures if now - t < 900]
        if len(failures) >= 10:
            flash(request, "error", "로그인 시도가 너무 많습니다. 15분 후 다시 시도하세요.")
            return redirect("/login")
        if app_password and secrets.compare_digest(password.encode(), app_password.encode()):
            failures.clear()
            request.session.clear()
            request.session["authed"] = True
            return redirect("/")
        failures.append(now)
        flash(request, "error", "비밀번호가 올바르지 않습니다.")
        return redirect("/login")

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form("")):
        check_csrf(request, csrf)
        request.session.clear()
        return redirect("/login" if app_password else "/")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def index(request: Request, db: Session = Depends(get_db)):
        complexes = list(db.scalars(select(Complex).where(Complex.active.is_(True)).order_by(Complex.gu, Complex.name)))
        intervals = setting(db, "freshness_days")
        rows = []
        for cx in complexes:
            cells = {}
            for sc in SIZE_CLASSES:
                for tx in ("SALE", "JEONSE", "WOLSE"):
                    best = None
                    for nature in ("ACTUAL", "ASKING"):
                        rec = latest_current(db, cx.id, tx, sc, nature)
                        fr = series_freshness(db, cx.id, tx, sc, nature, intervals)
                        if rec:
                            best = best or []
                            best.append((nature, rec, fr))
                    cells[(sc, tx)] = best or []
            rows.append((cx, cells))
        return render(request, "index.html", {"rows": rows, "watch_areas": setting(db, "watch_areas"), "nav": "home"})

    def _complex_from_form(cx: Complex, form) -> None:
        def opt_int(name):
            v = (form.get(name) or "").strip().replace(",", "")
            return int(v) if v else None

        def opt_float(name):
            v = (form.get(name) or "").strip().replace(",", "")
            if not v:
                return None
            f = float(v)
            if not math.isfinite(f) or f < 0:
                raise ValueError(name)
            return f

        name = (form.get("name") or "").strip()
        gu = (form.get("gu") or "").strip()
        if not name or not gu:
            raise RecordValidationError("단지명과 구는 필수입니다.")
        cx.name = name
        cx.gu = gu
        for f in ("aliases", "dong", "nearest_station", "molit_lawd_cd", "molit_apt_name", "hill_note", "daycare_other_options", "notes"):
            setattr(cx, f, (form.get(f) or "").strip())
        for f in (
            "building_year", "units", "station_distance_m", "station_walk_min", "daycare_anchor_distance_m",
            "daycare_anchor_minutes", "commute_1_min", "commute_2_min", "commute_3_min",
        ):
            setattr(cx, f, opt_int(f))
        cx.parking_per_unit = opt_float("parking_per_unit")
        cx.parking_is_estimate = form.get("parking_is_estimate") == "on"
        if cx.building_year and not (1950 <= cx.building_year <= date.today().year + 5):
            raise RecordValidationError("준공연도가 올바르지 않습니다.")
        existing = {u.size_class: u for u in cx.unit_types}
        for sc in SIZE_CLASSES:
            ex = opt_float(f"u{sc}_exclusive_m2")
            sp = opt_float(f"u{sc}_supply_m2")
            if ex is not None and size_class_for(ex) != sc:
                raise RecordValidationError(f"전용 {sc}㎡ 타입의 전용면적 {ex}㎡가 범위를 벗어났습니다. 공급면적을 입력하지 않았는지 확인하세요.")
            if ex is not None and sp is not None and sp < ex:
                raise RecordValidationError("공급면적은 전용면적보다 커야 합니다.")
            u = existing.get(sc)
            if u is None:
                u = UnitType(size_class=sc)
                cx.unit_types.append(u)
            u.exclusive_m2 = ex
            u.supply_m2 = sp

    @app.get("/complexes/new", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def complex_new(request: Request, db: Session = Depends(get_db)):
        return render(
            request,
            "complex_form.html",
            {"cx": None, "watch_areas": setting(db, "watch_areas"), "commutes": setting(db, "commute_destinations"),
             "anchor": setting(db, "daycare_anchor"), "nav": "complexes"},
        )

    @app.post("/complexes", dependencies=[Depends(auth)])
    async def complex_create(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        check_csrf(request, form.get("csrf", ""))
        cx = Complex(name="", gu="")
        cx.unit_types = []
        try:
            _complex_from_form(cx, form)
        except (RecordValidationError, ValueError) as exc:
            flash(request, "error", str(exc) if isinstance(exc, RecordValidationError) else "숫자 입력 형식을 확인하세요.")
            return redirect("/complexes/new")
        db.add(cx)
        db.commit()
        flash(request, "success", f"'{cx.name}' 단지를 추가했습니다.")
        return redirect(f"/complexes/{cx.id}")

    def _get_complex(db: Session, cid: int) -> Complex:
        cx = db.get(Complex, cid)
        if cx is None:
            raise HTTPException(404, "단지를 찾을 수 없습니다.")
        return cx

    @app.get("/complexes/{cid}", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def complex_detail(cid: int, request: Request, db: Session = Depends(get_db)):
        cx = _get_complex(db, cid)
        intervals = setting(db, "freshness_days")
        fresh = {}
        for sc in SIZE_CLASSES:
            for tx in ("SALE", "JEONSE", "WOLSE"):
                for nature in ("ACTUAL", "ASKING"):
                    fresh[(sc, tx, nature)] = series_freshness(db, cid, tx, sc, nature, intervals)
        recs = list(
            db.scalars(
                select(PriceRecord)
                .where(PriceRecord.complex_id == cid)
                .order_by(PriceRecord.tx_type, PriceRecord.size_class, PriceRecord.contract_date.desc(), PriceRecord.version.desc())
            )
        )
        return render(
            request,
            "complex_detail.html",
            {"cx": cx, "fresh": fresh, "records": recs, "commutes": setting(db, "commute_destinations"),
             "anchor": setting(db, "daycare_anchor"), "nav": "complexes"},
        )

    @app.get("/complexes/{cid}/edit", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def complex_edit(cid: int, request: Request, db: Session = Depends(get_db)):
        return render(
            request,
            "complex_form.html",
            {"cx": _get_complex(db, cid), "watch_areas": setting(db, "watch_areas"),
             "commutes": setting(db, "commute_destinations"), "anchor": setting(db, "daycare_anchor"), "nav": "complexes"},
        )

    @app.post("/complexes/{cid}", dependencies=[Depends(auth)])
    async def complex_update(cid: int, request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        check_csrf(request, form.get("csrf", ""))
        cx = _get_complex(db, cid)
        try:
            _complex_from_form(cx, form)
        except (RecordValidationError, ValueError) as exc:
            db.rollback()
            flash(request, "error", str(exc) if isinstance(exc, RecordValidationError) else "숫자 입력 형식을 확인하세요.")
            return redirect(f"/complexes/{cid}/edit")
        db.commit()
        flash(request, "success", "단지 정보를 저장했습니다.")
        return redirect(f"/complexes/{cid}")

    @app.post("/complexes/{cid}/remove", dependencies=[Depends(auth)])
    def complex_remove(cid: int, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        cx = _get_complex(db, cid)
        has_records = db.scalar(select(func.count(PriceRecord.id)).where(PriceRecord.complex_id == cid))
        if has_records:
            cx.active = False
            flash(request, "info", f"'{cx.name}'을 관심 목록에서 숨겼습니다. 가격 기록은 이력 보존을 위해 남겨둡니다.")
        else:
            db.delete(cx)
            flash(request, "info", f"'{cx.name}'을 삭제했습니다.")
        db.commit()
        return redirect("/complexes")

    @app.post("/complexes/{cid}/restore", dependencies=[Depends(auth)])
    def complex_restore(cid: int, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        cx = _get_complex(db, cid)
        cx.active = True
        db.commit()
        return redirect(f"/complexes/{cid}")

    @app.get("/complexes", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def complex_list(request: Request, db: Session = Depends(get_db)):
        cxs = list(db.scalars(select(Complex).order_by(Complex.active.desc(), Complex.gu, Complex.name)))
        return render(request, "complex_list.html", {"complexes": cxs, "watch_areas": setting(db, "watch_areas"), "nav": "complexes"})

    @app.get("/api/complexes/{cid}/series", dependencies=[Depends(auth)])
    def api_series(cid: int, request: Request, db: Session = Depends(get_db)):
        _get_complex(db, cid)
        qp = request.query_params
        tx = qp.get("tx_type", "SALE")
        sizes = qp.getlist("size_class") or list(SIZE_CLASSES)
        natures = qp.getlist("nature") or ["ACTUAL", "ASKING"]
        try:
            pts = series_points(db, cid, tx, sizes, natures)
        except RecordValidationError as exc:
            raise HTTPException(400, str(exc))
        intervals = setting(db, "freshness_days")
        groups: dict[tuple[str, str], list] = {}
        for r in pts:
            groups.setdefault((r.size_class, r.nature), []).append(r)
        series = []
        for (sc, nature), rs in sorted(groups.items()):
            fr = series_freshness(db, cid, tx, sc, nature, intervals)
            series.append(
                {
                    "size_class": sc,
                    "nature": nature,
                    "stale": fr.stale,
                    "last_updated": fr.last_updated.date().isoformat() if fr.last_updated else None,
                    "points": [
                        {
                            "id": r.id,
                            "record_uid": r.record_uid,
                            "version": r.version,
                            "date": r.observed_date.isoformat() if r.observed_date else None,
                            "price_krw": r.price_krw,
                            "deposit_krw": r.deposit_krw,
                            "monthly_rent_krw": r.monthly_rent_krw,
                            "floor": r.floor,
                            "status": r.status,
                            "is_estimate": r.is_estimate,
                            "source_name": r.source_name,
                            "detail_url": f"/records/{r.id}",
                        }
                        for r in rs
                    ],
                }
            )
        return {"tx_type": tx, "series": series}

    @app.get("/records/{rid}", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def record_detail(rid: int, request: Request, db: Session = Depends(get_db)):
        rec = db.get(PriceRecord, rid)
        if rec is None:
            raise HTTPException(404, "기록을 찾을 수 없습니다.")
        versions = list(
            db.scalars(select(PriceRecord).where(PriceRecord.record_uid == rec.record_uid).order_by(PriceRecord.version))
        )
        appends = list(db.scalars(select(SheetAppend).where(SheetAppend.record_uid == rec.record_uid)))
        return render(request, "record_detail.html", {"rec": rec, "versions": versions, "appends": appends, "nav": "complexes"})

    @app.get("/import", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def import_form(request: Request, db: Session = Depends(get_db), complex_id: int | None = None):
        cxs = list(db.scalars(select(Complex).where(Complex.active.is_(True)).order_by(Complex.name)))
        return render(request, "import_paste.html", {"complexes": cxs, "complex_id": complex_id, "nav": "import"})

    @app.post("/import/parse", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def import_parse(request: Request, text: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        cxs = list(db.scalars(select(Complex).where(Complex.active.is_(True)).order_by(Complex.name)))
        parsed = parse_listing(text, [ComplexRef(c.id, c.name, c.alias_list) for c in cxs])
        return render(
            request,
            "import_confirm.html",
            {"p": parsed, "raw": text, "complexes": cxs, "today": date.today().isoformat(), "manual": False, "nav": "import"},
        )

    @app.get("/import/manual", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def import_manual(request: Request, db: Session = Depends(get_db), complex_id: int | None = None):
        cxs = list(db.scalars(select(Complex).where(Complex.active.is_(True)).order_by(Complex.name)))
        parsed = parse_listing("", [])
        parsed.complex_id = complex_id
        return render(
            request,
            "import_confirm.html",
            {"p": parsed, "raw": "", "complexes": cxs, "today": date.today().isoformat(), "manual": True, "nav": "import"},
        )

    def _candidate_from_form(form) -> Candidate:
        def opt_float(name):
            v = (form.get(name) or "").strip().replace(",", "")
            if not v:
                return None
            f = float(v)
            if not math.isfinite(f) or f <= 0:
                raise ValueError(name)
            return f

        def opt_date(name):
            v = (form.get(name) or "").strip()
            return date.fromisoformat(v) if v else None

        def amount(name: str, label: str, example: str) -> int:
            value, err = parse_krw_strict(form.get(name))
            if err:
                raise RecordValidationError(f"{label}: {err}")
            if value is None:
                raise RecordValidationError(f"{label}을(를) 입력하세요 (예: {example}).")
            return value

        tx = form.get("tx_type") or ""
        price = deposit = monthly = None
        if tx == "SALE":
            price = amount("price", "매매가", "12억 5,000")
        elif tx == "JEONSE":
            deposit = amount("deposit", "전세 보증금", "7억")
        elif tx == "WOLSE":
            deposit = amount("deposit", "월세 보증금", "1억")
            monthly = parse_manwon(form.get("monthly_rent_man"))
            if monthly is None:
                raise RecordValidationError("월세는 보증금과 월세(만원, 정수)를 함께 입력해야 합니다.")
        else:
            raise RecordValidationError("거래유형을 선택하세요.")
        cid = form.get("complex_id")
        if not cid:
            raise RecordValidationError("단지를 선택하세요.")
        return Candidate(
            complex_id=int(cid),
            size_class=form.get("size_class") or "",
            tx_type=tx,
            nature=form.get("nature") or "",
            source_name=(form.get("source_name") or "").strip(),
            price_krw=price,
            deposit_krw=deposit,
            monthly_rent_krw=monthly,
            exclusive_m2=opt_float("exclusive_m2"),
            supply_m2=opt_float("supply_m2"),
            floor=(form.get("floor") or "").strip(),
            contract_date=opt_date("contract_date"),
            report_date=opt_date("report_date"),
            source_url=(form.get("source_url") or "").strip(),
            source_record_id=(form.get("source_record_id") or "").strip() or None,
            source_version=(form.get("source_version") or "").strip() or None,
            raw_snippet=(form.get("raw_snippet") or "")[:20000],
            status=form.get("status") or "ACTIVE",
            is_estimate=form.get("is_estimate") == "on",
            estimate_note=(form.get("estimate_note") or "").strip(),
        )

    @app.post("/import/confirm", dependencies=[Depends(auth)])
    async def import_confirm(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        check_csrf(request, form.get("csrf", ""))
        if form.get("confirmed") != "on":
            flash(request, "error", "내용을 확인했다는 체크박스를 선택해야 저장됩니다.")
            return redirect("/import")
        try:
            cand = _candidate_from_form(form)
            res = ingest(db, cand)
        except (RecordValidationError, ValueError) as exc:
            db.rollback()
            msg = str(exc) if isinstance(exc, RecordValidationError) else "입력 형식(날짜/숫자)을 확인하세요."
            flash(request, "error", "저장하지 않았습니다: " + msg)
            return redirect("/import")
        db.commit()
        if res.outcome == "created":
            flash(request, "success", "새 기록을 저장했습니다.")
        elif res.outcome == "new_version":
            flash(request, "success", f"출처 데이터 변경을 새 버전(v{res.record.version})으로 저장했습니다.")
        elif res.outcome == "duplicate":
            flash(request, "info", "이미 같은 기록이 있어 새로 저장하지 않았습니다.")
        else:
            flash(request, "warn", "기존 기록과 일부만 일치합니다. 병합하지 않고 검토 대기열에 넣었습니다.")
            return redirect(f"/review/{res.review.id}")
        if res.outcome != "duplicate":
            try_auto_sync(db, request)
        return redirect(f"/records/{res.record.id}")

    @app.get("/review", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def review_list(request: Request, db: Session = Depends(get_db)):
        items = list(db.scalars(select(ReviewItem).order_by(ReviewItem.status != "PENDING", ReviewItem.created_at.desc())))
        cxs = {c.id: c for c in db.scalars(select(Complex))}
        return render(request, "review_list.html", {"items": items, "cxs": cxs, "nav": "review"})

    @app.get("/review/{rid}", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def review_detail(rid: int, request: Request, db: Session = Depends(get_db)):
        item = db.get(ReviewItem, rid)
        if item is None:
            raise HTTPException(404, "검토 항목을 찾을 수 없습니다.")
        cand = Candidate.from_json(item.candidate)
        cx = db.get(Complex, cand.complex_id)
        return render(request, "review_detail.html", {"item": item, "cand": cand, "cx": cx, "nav": "review"})

    @app.post("/review/{rid}", dependencies=[Depends(auth)])
    def review_resolve(rid: int, request: Request, action: str = Form(...), csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        if action not in ("separate", "new_version", "discard"):
            raise HTTPException(400, "알 수 없는 처리 방법입니다.")
        item = db.get(ReviewItem, rid)
        if item is None:
            raise HTTPException(404, "검토 항목을 찾을 수 없습니다.")
        try:
            rec = resolve_review(db, item, action)
        except RecordValidationError as exc:
            db.rollback()
            flash(request, "error", str(exc))
            return redirect(f"/review/{rid}")
        db.commit()
        flash(request, "success", {"separate": "별개 거래로 저장했습니다.", "new_version": "기존 기록의 새 버전으로 저장했습니다.", "discard": "후보를 버렸습니다."}[action])
        if rec:
            try_auto_sync(db, request)
            return redirect(f"/records/{rec.id}")
        return redirect("/review")

    @app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def settings_page(request: Request, db: Session = Depends(get_db)):
        conn = sheet_sync.active_connection(db)
        pending = len(sheet_sync.pending_records(db, conn)) if conn else 0
        return render(
            request,
            "settings.html",
            {
                "secret_status": store.status(db),
                "secret_labels": KNOWN_SECRETS,
                "google_connected": tokens.is_connected(db),
                "redirect_uri": base_url + "/oauth/google/callback",
                "conn": conn,
                "pending_sync": pending,
                "proposed_tab": sheet_sync.PROPOSED_TAB,
                "proposed_plan": sheet_sync.propose_new_tab_plan(),
                "settings": {k: setting(db, k) for k in DEFAULT_SETTINGS},
                "nav": "settings",
            },
        )

    @app.post("/settings/secrets", dependencies=[Depends(auth)])
    def settings_secret(request: Request, name: str = Form(...), value: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        if name not in KNOWN_SECRETS or name == "google_refresh_token":
            raise HTTPException(400, "알 수 없는 항목입니다.")
        try:
            store.set(db, name, value.strip())
        except SecretStoreError as exc:
            flash(request, "error", str(exc))
            return redirect("/settings")
        db.commit()
        flash(request, "success", f"{KNOWN_SECRETS[name]}을(를) 서버에 암호화 저장했습니다.")
        return redirect("/settings")

    @app.post("/settings/general", dependencies=[Depends(auth)])
    async def settings_general(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        check_csrf(request, form.get("csrf", ""))
        try:
            fr = {"ACTUAL": int(form.get("fresh_actual") or 45), "ASKING": int(form.get("fresh_asking") or 14)}
            if min(fr.values()) < 1:
                raise ValueError
        except ValueError:
            flash(request, "error", "갱신 주기는 1일 이상의 정수여야 합니다.")
            return redirect("/settings")
        dests = [(form.get(f"commute_{i}") or "").strip() for i in (1, 2, 3)]
        areas = []
        for line in (form.get("watch_areas") or "").splitlines():
            if not line.strip():
                continue
            gu, _, rest = line.partition(":")
            dongs = [d.strip() for d in rest.split(",") if d.strip()]
            areas.append({"gu": gu.strip(), "dongs": dongs, "note": ""})
        anchor = {"name": (form.get("anchor_name") or "").strip(), "enrollment": (form.get("anchor_enrollment") or "").strip()}
        for k, v in (
            ("freshness_days", fr),
            ("commute_destinations", dests),
            ("watch_areas", areas),
            ("daycare_anchor", anchor),
            ("auto_sheet_sync", form.get("auto_sheet_sync") == "on"),
        ):
            row = db.get(Setting, k)
            if row is None:
                db.add(Setting(key=k, value=v))
            else:
                row.value = v
        db.commit()
        flash(request, "success", "설정을 저장했습니다.")
        return redirect("/settings")

    @app.post("/oauth/google/start", dependencies=[Depends(auth)])
    def oauth_start(request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        try:
            cid, _ = tokens.client_config(db)
        except sheet_sync.SetupRequired as exc:
            flash(request, "error", str(exc))
            return redirect("/settings")
        verifier, challenge = google_oauth.new_pkce()
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        request.session["oauth_verifier"] = verifier
        return RedirectResponse(
            google_oauth.authorization_url(cid, base_url + "/oauth/google/callback", state, challenge), status_code=303
        )

    @app.get("/oauth/google/callback", dependencies=[Depends(auth)])
    def oauth_callback(request: Request, db: Session = Depends(get_db), code: str = "", state: str = "", error: str = ""):
        expected = request.session.pop("oauth_state", None)
        verifier = request.session.pop("oauth_verifier", None)
        if error:
            flash(request, "error", "Google 로그인이 취소되었거나 거부되었습니다.")
            return redirect("/settings")
        if not expected or not state or not secrets.compare_digest(state, expected) or not verifier:
            flash(request, "error", "OAuth 상태 값이 일치하지 않아 중단했습니다. 다시 시도하세요.")
            return redirect("/settings")
        try:
            cid, csec = tokens.client_config(db)
            bundle = google_oauth.exchange_code(http, cid, csec, code, base_url + "/oauth/google/callback", verifier)
            tokens.save_initial(db, bundle)
            db.commit()
        except (google_oauth.OAuthError, sheet_sync.SetupRequired) as exc:
            flash(request, "error", str(exc))
            return redirect("/settings")
        except httpx.HTTPError:
            flash(request, "error", "Google에 연결할 수 없습니다.")
            return redirect("/settings")
        flash(request, "success", "Google 계정을 연결했습니다. 이제 워크북 URL을 입력하세요.")
        return redirect("/settings#sheet")

    @app.post("/oauth/google/disconnect", dependencies=[Depends(auth)])
    def oauth_disconnect(request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        tokens.disconnect(db)
        conn = sheet_sync.active_connection(db)
        if conn:
            conn.state = "ABANDONED"
        db.commit()
        flash(request, "info", "Google 연결을 해제했습니다.")
        return redirect("/settings")

    def _sheet_action(request: Request, db: Session, fn, ok_msg: str):
        try:
            fn()
            db.commit()
            if ok_msg:
                flash(request, "success", ok_msg)
        except google_oauth.ReconnectRequired as exc:
            db.rollback()
            flash(request, "warn", str(exc))
        except (SheetsError, sheet_sync.SetupRequired, google_oauth.OAuthError) as exc:
            db.rollback()
            flash(request, "error", str(exc))
        except httpx.HTTPError:
            db.rollback()
            flash(request, "error", "Google에 연결할 수 없습니다. 아무 것도 쓰지 않았습니다.")
        return redirect("/settings#sheet")

    def _conn_or_404(db: Session, conn_id: int) -> SheetConnection:
        conn = db.get(SheetConnection, conn_id)
        if conn is None or conn.state == "ABANDONED":
            raise HTTPException(404, "연결 정보를 찾을 수 없습니다.")
        return conn

    @app.post("/sheet/connect", dependencies=[Depends(auth)])
    def sheet_connect(request: Request, url: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        return _sheet_action(request, db, lambda: sheet_sync.start_connection(db, tokens, url), "")

    @app.post("/sheet/{conn_id}/confirm", dependencies=[Depends(auth)])
    def sheet_confirm(conn_id: int, request: Request, email: str = Form(""), title: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        conn = _conn_or_404(db, conn_id)
        return _sheet_action(
            request, db, lambda: sheet_sync.confirm_destination(db, conn, email, title),
            "워크북을 확인했습니다. 관측 기록을 추가할 탭을 고르세요.",
        )

    @app.post("/sheet/{conn_id}/cancel", dependencies=[Depends(auth)])
    def sheet_cancel(conn_id: int, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        conn = _conn_or_404(db, conn_id)
        conn.state = "ABANDONED"
        db.commit()
        flash(request, "info", "워크북 연결을 취소했습니다. 아무 것도 쓰지 않았습니다.")
        return redirect("/settings#sheet")

    @app.post("/sheet/{conn_id}/tab", dependencies=[Depends(auth)])
    def sheet_tab(conn_id: int, request: Request, tab: str = Form(""), header_row: int = Form(1), csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        conn = _conn_or_404(db, conn_id)
        if header_row < 1:
            header_row = 1
        return _sheet_action(
            request, db, lambda: sheet_sync.read_tab_structure(db, tokens, conn, tab, header_row),
            "탭 구조를 읽었습니다. 열 배치안을 확인 후 승인하세요.",
        )

    @app.post("/sheet/{conn_id}/new-tab", dependencies=[Depends(auth)])
    def sheet_new_tab(conn_id: int, request: Request, approve: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        conn = _conn_or_404(db, conn_id)
        if approve != "yes":
            flash(request, "error", "새 탭 생성을 승인하지 않았습니다.")
            return redirect("/settings#sheet")
        return _sheet_action(
            request, db, lambda: sheet_sync.approve_new_tab(db, tokens, conn),
            f"'{sheet_sync.PROPOSED_TAB}' 탭을 만들었습니다. 열 배치안을 승인하세요.",
        )

    @app.post("/sheet/{conn_id}/approve-plan", dependencies=[Depends(auth)])
    def sheet_approve(conn_id: int, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        conn = _conn_or_404(db, conn_id)
        return _sheet_action(
            request, db, lambda: sheet_sync.approve_plan(db, tokens, conn),
            "열 배치를 승인했습니다. 이제 관측 기록을 추가할 수 있습니다.",
        )

    @app.post("/sheet/sync", dependencies=[Depends(auth)])
    def sheet_sync_now(request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
        check_csrf(request, csrf)
        conn = sheet_sync.active_connection(db)
        result = {}

        def run():
            result.update(sheet_sync.sync(db, tokens, conn))

        resp = _sheet_action(request, db, run, "")
        if result:
            flash(request, "success", f"추가 {result['appended']}행, 이미 시트에 있던 항목 {result['already_present']}건.")
        return resp

    return app


def _app_from_env():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return create_app()


if os.environ.get("HM_AUTOCREATE", "1") == "1" and (os.environ.get("HM_MASTER_KEY") or os.environ.get("HM_ENV") == "production"):
    app = _app_from_env()
