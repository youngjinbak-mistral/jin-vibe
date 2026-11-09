import re
from dataclasses import dataclass, field
from datetime import date

from app.money import EOK, MASK, MoneyToken, scan_money

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
    if not found and re.search(r"보증금[^\n]*?월(?:세|임대료)?\s*[:：]?\s*\d", t):
        found.add("WOLSE")
    if len(found) > 1:
        warnings.append(WARN_MULTI_TYPE)
        return None
    return next(iter(found), None)


def _detect_nature(text: str) -> str:
    if "실거래" in text or "계약일" in text or "거래일" in text:
        return "ACTUAL"
    return "ASKING"


_MASK_PATTERNS = [
    re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
    re.compile(r"(?<!\d)\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}\.?(?!\d)"),
    re.compile(r"(?<![\d.])\d{2}\.\d{1,2}\.\d{1,2}\.?(?!\d)"),
    re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*(?:㎡|m²|m2|제곱미터|평)"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:㎡|m²|m2|제곱미터|평)"),
    re.compile(r"(?:\d{1,3}|저|중|고)\s*/\s*\d{1,3}\s*층"),
    re.compile(r"(?:지하\s*)?\d{1,3}\s*층"),
    re.compile(r"\d+\s*(?:동|호|세대|개동|대|년차|년식|년|개월|분|초|m|km|%|퍼센트|타입|형)(?![가-힣])"),
    re.compile(r"(?<!\d)(?:59|84)\s*[A-Za-z](?![A-Za-z])"),
    re.compile(r"(?:\+?82[-\s]?|0)\d{1,2}[-\s]\d{3,4}[-\s]\d{4}"),
]

_LABELS = [
    ("월임대료", "monthly"),
    ("월세금", "monthly"),
    ("반전세", "wolse"),
    ("월세", "wolse"),
    ("전세보증금", "deposit"),
    ("보증금", "deposit"),
    ("전세가", "jeonse"),
    ("전세금", "jeonse"),
    ("전세", "jeonse"),
    ("매매가", "sale"),
    ("매매", "sale"),
    ("매도가", "sale"),
    ("실거래가", "generic"),
    ("거래가", "generic"),
    ("호가", "generic"),
    ("가격", "generic"),
    ("관리비", "other"),
    ("융자", "other"),
    ("대출", "other"),
    ("채권최고액", "other"),
    ("시세", "other"),
    ("공시", "other"),
    ("취득세", "other"),
    ("세금", "other"),
    ("수수료", "other"),
    ("중개", "other"),
    ("분양가", "other"),
    ("하한", "other"),
    ("상한", "other"),
    ("평균", "other"),
    ("최고", "other"),
    ("최저", "other"),
    ("이전", "other"),
    ("기존", "other"),
    ("직전", "other"),
    ("월", "monthly"),
]
_LABEL_RE = re.compile("|".join(re.escape(k) for k, _ in _LABELS))
_LABEL_KIND = dict(_LABELS)

WARN_AMOUNT_AMBIGUOUS = "금액 '{frag}'을(를) 확정할 수 없습니다: {reason}. 금액 칸에 직접 입력하세요"
WARN_AMOUNT_MULTIPLE = "{field} 후보가 여러 개입니다 ({values}). 금액 칸에 직접 입력하세요"
WARN_AMOUNT_IMPLAUSIBLE = "{field} {value}원은 비정상적인 값입니다. 금액 칸에 직접 입력하세요"
WARN_AMOUNT_MISSING = "{field}을(를) 찾지 못했습니다. 금액 칸에 직접 입력하세요"


def mask_non_money(text: str) -> str:
    chars = list(text)
    for pat in _MASK_PATTERNS:
        for m in pat.finditer(text):
            if m.group(0).endswith("월") and "월" in m.group(0) and not re.search(r"\d\s*일", m.group(0)):
                continue
            for i in range(m.start(), m.end()):
                if chars[i] != "\n":
                    chars[i] = MASK
    return "".join(chars)


def _label_in(segment: str, last: bool) -> str | None:
    found = None
    for m in _LABEL_RE.finditer(segment):
        k = m.group(0)
        if k == "전세" and m.start() > 0 and segment[m.start() - 1] == "반":
            continue
        if k == "월" and m.end() < len(segment) and segment[m.end()] in "세임":
            continue
        found = _LABEL_KIND[k]
        if not last:
            return found
    return found


@dataclass
class _Money:
    tok: MoneyToken
    label: str
    frag: str
    pair_with: int | None = None


def _label_tokens(masked: str, tokens: list[MoneyToken]) -> list[_Money]:
    out = []
    for i, t in enumerate(tokens):
        prev_end = tokens[i - 1].end if i else 0
        line_start = masked.rfind("\n", 0, t.start) + 1
        seg = masked[max(prev_end, line_start) : t.start]
        label = _label_in(seg, last=True)
        if label is None:
            nxt = tokens[i + 1].start if i + 1 < len(tokens) else len(masked)
            line_end = masked.find("\n", t.end)
            line_end = len(masked) if line_end < 0 else line_end
            trail = masked[t.end : min(nxt, line_end)]
            trail_label = _label_in(trail[:6], last=False)
            if trail_label in ("sale", "jeonse", "wolse"):
                label = trail_label
        out.append(_Money(t, label or "generic", masked[t.start : t.end].strip()))
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        between = masked[a.tok.end : b.tok.start]
        if re.fullmatch(r"\s*/\s*", between):
            a.pair_with = i + 1
            b.label = "pair_monthly"
    return out


def _directly_labeled(masked: str, m: _Money) -> bool:
    seg = masked[: m.tok.start].rstrip(" \t:：")
    return bool(_LABEL_RE.search(seg[-6:])) and seg[-1:] not in ("", "\n", MASK)


def _usable(masked: str, m: _Money) -> bool:
    if m.label in ("other",):
        return False
    if m.tok.explicit:
        return True
    return m.label != "generic" and (_directly_labeled(masked, m) or m.label == "pair_monthly")


def _pick(field: str, cands: list[_Money], warnings: list[str], lo: int, hi: int) -> int | None:
    if not cands:
        return None
    for c in cands:
        if c.tok.ambiguous:
            warnings.append(WARN_AMOUNT_AMBIGUOUS.format(frag=c.frag, reason=c.tok.reason))
            return None
    values = sorted({c.tok.value for c in cands})
    if len(values) > 1:
        warnings.append(WARN_AMOUNT_MULTIPLE.format(field=field, values=", ".join(c.frag for c in cands)))
        return None
    v = values[0]
    if not (lo <= v <= hi):
        warnings.append(WARN_AMOUNT_IMPLAUSIBLE.format(field=field, value=f"{v:,}"))
        return None
    return v


def _parse_prices(text: str, tx_type: str, warnings: list[str]):
    masked = mask_non_money(text)
    ms = [m for m in _label_tokens(masked, scan_money(masked)) if _usable(masked, m)]
    primary_range = (10_000_000, 1_000 * EOK)
    if tx_type == "SALE":
        cands = [m for m in ms if m.label == "sale" or (m.label == "generic" and m.tok.explicit)]
        price = _pick("매매가", cands, warnings, *primary_range)
        if price is None and not cands:
            warnings.append(WARN_AMOUNT_MISSING.format(field="매매가"))
        return price, None, None
    if tx_type == "JEONSE":
        cands = [m for m in ms if m.label in ("jeonse", "deposit") or (m.label == "generic" and m.tok.explicit)]
        dep = _pick("전세 보증금", cands, warnings, *primary_range)
        if dep is None and not cands:
            warnings.append(WARN_AMOUNT_MISSING.format(field="전세 보증금"))
        return None, dep, None
    dep_c: list[_Money] = []
    mon_c: list[_Money] = []
    for m in ms:
        if m.label == "pair_monthly":
            mon_c.append(m)
        elif m.pair_with is not None and m.label in ("wolse", "deposit", "generic"):
            dep_c.append(m)
        elif m.label == "deposit":
            dep_c.append(m)
        elif m.label == "monthly":
            mon_c.append(m)
        elif m.label == "wolse":
            (mon_c if dep_c else dep_c).append(m)
    deposit = _pick("월세 보증금", dep_c, warnings, 0, 1_000 * EOK)
    monthly = _pick("월세", mon_c, warnings, 10_000, 100_000_000)
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
