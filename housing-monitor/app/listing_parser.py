import re
from dataclasses import dataclass, field
from datetime import date

from app.money import parse_krw, parse_manwon

PYEONG_M2 = 3.305785


@dataclass
class ComplexRef:
    id: int
    name: str
    aliases: list[str]


@dataclass
class ParsedListing:
    complex_id: int | None
    complex_name_guess: str | None
    tx_type: str | None
    nature: str
    price_krw: int | None
    deposit_krw: int | None
    monthly_rent_krw: int | None
    exclusive_m2: float | None
    supply_m2: float | None
    size_class: str | None
    floor: str | None
    observed_date: str | None
    source_name: str | None
    source_url: str | None
    source_listing_id: str | None
    warnings: list[str] = field(default_factory=list)


_AMT = r"\d[\d,]*(?:\.\d+)?\s*억(?:\s*\d[\d,]*(?:\s*천)?(?:\s*만)?)?|\d[\d,]*(?:\.\d+)?\s*천(?:\s*만)?|\d[\d,]*(?:\s*만)?"
_NUM = r"\d+(?:\.\d+)?"
_AREA_UNIT = r"(?:㎡|m²|m2|제곱미터)"
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_NAVER_HOSTS = ("land.naver.com", "new.land.naver.com", "m.land.naver.com", "fin.land.naver.com")

WARN_MULTI_TYPE = "거래유형이 여러 개 감지됨"
WARN_WOLSE_PAIR = "월세는 보증금과 월세를 함께 입력해야 합니다"
WARN_AREA_ASSUMED = "면적 구분(전용/공급)이 명시되지 않아 전용으로 가정"
WARN_TYPE_LABEL = "타입 표기로 평형을 추정했습니다. 전용면적을 확인하세요"
WARN_COMPLEX_TIE = "여러 단지가 동일하게 매칭되어 단지를 특정할 수 없습니다"


def _strip_urls(text: str) -> str:
    return _URL_RE.sub(" ", text)


def _detect_tx(text: str, warnings: list[str]) -> str | None:
    found = set()
    t = text.replace("반전세", " 월세 ")
    if "매매" in t:
        found.add("SALE")
    if "전세" in t:
        found.add("JEONSE")
    if "월세" in t:
        found.add("WOLSE")
    if not found and re.search(r"보증금\s*(?:" + _AMT + r")\s*[/,]?\s*월(?:세)?\s*\d", t):
        found.add("WOLSE")
    if len(found) > 1:
        warnings.append(WARN_MULTI_TYPE)
        return None
    return next(iter(found), None)


def _detect_nature(text: str) -> str:
    if "실거래" in text or "계약일" in text or "거래일" in text:
        return "ACTUAL"
    return "ASKING"


def _amount(s: str | None) -> int | None:
    if not s:
        return None
    return parse_krw(re.sub(r"\s+", "", s))


def _parse_prices(text: str, tx_type: str, warnings: list[str]):
    if tx_type == "SALE":
        m = re.search(r"매매(?:가)?\s*[:：]?\s*(" + _AMT + r")", text)
        return (_amount(m.group(1)) if m else None), None, None
    if tx_type == "JEONSE":
        m = re.search(r"(?<!반)전세(?:가|금)?\s*[:：]?\s*(" + _AMT + r")", text)
        if not m:
            m = re.search(r"보증금\s*[:：]?\s*(" + _AMT + r")", text)
        return None, (_amount(m.group(1)) if m else None), None
    deposit = monthly = None
    m = re.search(r"(?:반전세|월세)\s*[:：]?\s*(" + _AMT + r")\s*/\s*(\d[\d,]*)", text)
    if m:
        deposit, monthly = _amount(m.group(1)), parse_manwon(m.group(2))
    else:
        d = re.search(r"보증금\s*[:：]?\s*(" + _AMT + r")", text)
        r = re.search(r"월(?:세|임대료)?\s*[:：]?\s*(\d[\d,]*)\s*(?:만)?(?!\s*[억천])(?!\s*\d)", text[d.end():] if d else text)
        if d:
            deposit = _amount(d.group(1))
        if r:
            monthly = parse_manwon(r.group(1))
    if deposit is None or monthly is None:
        warnings.append(WARN_WOLSE_PAIR)
        return None, None, None
    return None, deposit, monthly


def _parse_areas(text: str, warnings: list[str]):
    exclusive = supply = None
    pair = re.search(r"(" + _NUM + r")\s*/\s*(" + _NUM + r")\s*" + _AREA_UNIT, text)
    if pair:
        return float(pair.group(2)), float(pair.group(1))
    sup = re.search(r"공급(?:면적)?\s*[:：]?\s*(" + _NUM + r")\s*" + _AREA_UNIT + "?", text)
    exc = re.search(r"전용(?:면적)?\s*[:：]?\s*(" + _NUM + r")\s*" + _AREA_UNIT + "?", text)
    if sup:
        supply = float(sup.group(1))
    if exc:
        exclusive = float(exc.group(1))
    if supply is None:
        py = re.search(r"(?<![\d.])(" + _NUM + r")\s*평(?!균)", text)
        if py:
            supply = round(float(py.group(1)) * PYEONG_M2, 2)
    if exclusive is None and not sup:
        rest = text
        for m in (sup, exc):
            if m:
                rest = rest.replace(m.group(0), " ")
        lone = re.search(r"(?<![\d./])(" + _NUM + r")\s*" + _AREA_UNIT, rest)
        if lone:
            exclusive = float(lone.group(1))
            warnings.append(WARN_AREA_ASSUMED)
    return exclusive, supply


def size_class_for(exclusive: float | None) -> str | None:
    if exclusive is None:
        return None
    if 57.0 <= exclusive < 63.0:
        return "59"
    if 82.0 <= exclusive < 87.0:
        return "84"
    return None


def _parse_floor(text: str) -> str | None:
    m = re.search(r"(?<!\d)(\d{1,3}|저|중|고)\s*/\s*\d{1,3}\s*층", text)
    if m:
        return m.group(1)
    m = re.search(r"(?<![\d/])(\d{1,3})\s*층", text)
    if m:
        return m.group(1)
    m = re.search(r"(저|중|고)층", text)
    if m:
        return m.group(1)
    return None


def _valid(y: int, mo: int, d: int) -> str | None:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _parse_date(text: str) -> str | None:
    patterns = [
        (r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", 0),
        (r"(?<!\d)(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?!\d)", 0),
        (r"(?<![\d.])(\d{2})\.(\d{1,2})\.(\d{1,2})(?!\d)", 2000),
    ]
    found = []
    for pat, base in patterns:
        for m in re.finditer(pat, text):
            iso = _valid(base + int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if iso:
                found.append((m.start(), iso))
    if not found:
        return None
    for kw in ("확인", "등록", "계약일", "거래일"):
        idx = text.find(kw)
        if idx >= 0:
            after = [f for f in found if f[0] >= idx]
            if after:
                return min(after)[1]
    return min(found)[1]


def _detect_source(text: str):
    url_m = _URL_RE.search(text)
    url = url_m.group(0) if url_m else None
    lowered = text.lower()
    source = listing_id = None
    if any(h in lowered for h in _NAVER_HOSTS) or "네이버" in text:
        source = "Naver 부동산"
        if url:
            m = re.search(r"articleNo=(\d+)", url) or re.search(r"/articles/(\d+)", url)
            if m:
                listing_id = m.group(1)
    elif "hogangnono.com" in lowered or "호갱노노" in text:
        source = "호갱노노"
    return source, url, listing_id


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _match_complex(text: str, complexes: list[ComplexRef], warnings: list[str]):
    norm = _norm(text)
    best: dict[int, tuple[int, str]] = {}
    for c in complexes:
        for name in [c.name, *c.aliases]:
            n = _norm(name or "")
            if n and n in norm:
                if c.id not in best or len(n) > best[c.id][0]:
                    best[c.id] = (len(n), c.name)
    if not best:
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip() and not _URL_RE.fullmatch(ln.strip())), "")
        return None, (first_line[:100] or None)
    top = max(v[0] for v in best.values())
    winners = [(cid, v[1]) for cid, v in best.items() if v[0] == top]
    if len(winners) > 1:
        warnings.append(WARN_COMPLEX_TIE)
        return None, winners[0][1]
    return winners[0]


def parse_listing(text: str, complexes: list[ComplexRef], today: date | None = None) -> ParsedListing:
    if not isinstance(text, str):
        text = ""
    text = text[:20000]
    warnings: list[str] = []
    body = _strip_urls(text)
    tx_type = _detect_tx(body, warnings)
    price = deposit = monthly = None
    if tx_type:
        price, deposit, monthly = _parse_prices(body, tx_type, warnings)
    exclusive, supply = _parse_areas(body, warnings)
    size_class = size_class_for(exclusive)
    if exclusive is None:
        tm = re.search(r"(?<!\d)(59|84)\s*[A-Za-z]\s*(?:타입|형)?", body)
        if tm:
            size_class = tm.group(1)
            warnings.append(WARN_TYPE_LABEL)
    source, url, listing_id = _detect_source(text)
    cid, name_guess = _match_complex(body, complexes, warnings)
    return ParsedListing(
        complex_id=cid,
        complex_name_guess=name_guess,
        tx_type=tx_type,
        nature=_detect_nature(body),
        price_krw=price,
        deposit_krw=deposit,
        monthly_rent_krw=monthly,
        exclusive_m2=exclusive,
        supply_m2=supply,
        size_class=size_class,
        floor=_parse_floor(body),
        observed_date=_parse_date(body),
        source_name=source,
        source_url=url,
        source_listing_id=listing_id,
        warnings=warnings,
    )
