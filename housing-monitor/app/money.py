import re

EOK = 100_000_000
MAN = 10_000

_NUM = r"\d[\d,]*(?:\.\d+)?"
_KRW_RE = re.compile(rf"(?:(?P<eok>{_NUM})억)?(?:(?P<cheon>{_NUM})천(?:만)?)?(?:(?P<man>{_NUM})(?:만)?)?")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_krw(text) -> int | None:
    if text is None:
        return None
    s = str(text).strip().replace(" ", "").replace("원", "")
    if not s:
        return None
    m = _KRW_RE.fullmatch(s)
    if not m or not any(m.groupdict().values()):
        return None
    total = 0
    if m["eok"]:
        total += round(_num(m["eok"]) * EOK)
    if m["cheon"]:
        total += round(_num(m["cheon"]) * 1000 * MAN)
    if m["man"]:
        total += round(_num(m["man"]) * MAN)
    return total


def parse_manwon(text) -> int | None:
    if text is None:
        return None
    s = str(text).strip().replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+", s):
        return None
    return int(s) * MAN


def format_krw(amount: int | None) -> str:
    if amount is None:
        return "-"
    neg = amount < 0
    eok, rem = divmod(abs(int(amount)), EOK)
    man, won = divmod(rem, MAN)
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    if not parts:
        out = f"{won:,}원"
    else:
        out = " ".join(parts) + "원"
        if won:
            out += f" (+{won:,}원)"
    return ("-" if neg else "") + out


def format_eok(amount: int | None, digits: int = 2) -> str:
    if amount is None:
        return "-"
    return f"{amount / EOK:.{digits}f}억"
