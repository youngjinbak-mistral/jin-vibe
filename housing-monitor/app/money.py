import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

EOK = 100_000_000
CHEONMAN = 10_000_000
MAN = 10_000

MASK = "\0"

_NUM_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?![\d,])|\d+)(\.\d+)?")
_HSPACE = " \t\u00a0\u3000"
_SUB_BOUNDARY = "\n\r,;/)]|·" + MASK

AMBIG_SUB_SMALL = "억 뒤의 작은 숫자는 만원인지 천만원인지 불분명합니다 (예: '12억 5,000' 또는 '12억 5천'으로 입력)"
AMBIG_SUB_WON = "억 뒤 숫자에 '원'만 붙어 있어 단위가 불분명합니다 (예: '12억 5,000만원')"
AMBIG_SUB_LARGE = "억 뒤 숫자가 너무 큽니다 (만원 단위는 9,999까지)"
AMBIG_DECIMAL = "소수점 금액은 억/만 단위와 함께 입력하세요"
AMBIG_NOT_INTEGER = "원 단위 정수로 떨어지지 않는 금액입니다"
AMBIG_CHEON = "'천' 앞에는 1~9의 정수만 올 수 있습니다"
AMBIG_BARE_LARGE = "단위 없는 큰 숫자는 원인지 만원인지 불분명합니다 (예: '12억' 또는 '1,200,000,000원')"
AMBIG_GROUPING = "쉼표 자리수가 올바르지 않습니다"
ERR_UNPARSEABLE = "금액 형식을 이해할 수 없습니다 (예: 12억 5,000 / 8억 / 5,000만원 / 250)"
ERR_MULTIPLE = "금액이 두 개 이상 들어 있습니다. 하나만 입력하세요"
ERR_NEGATIVE = "음수 금액은 입력할 수 없습니다"


@dataclass
class MoneyToken:
    start: int
    end: int
    value: int | None
    explicit: bool
    reason: str | None = None

    @property
    def ambiguous(self) -> bool:
        return self.value is None


def _skip_h(text: str, i: int) -> int:
    while i < len(text) and text[i] in _HSPACE:
        i += 1
    return i


def _char(text: str, i: int) -> str:
    return text[i] if 0 <= i < len(text) else ""


def _dec(m: re.Match) -> tuple[Decimal, bool]:
    return Decimal(m.group(1).replace(",", "") + (m.group(2) or "")), bool(m.group(2))


def _is_word_char(c: str) -> bool:
    return bool(c) and (c.isalnum() or c in "._")


def _consume_won(text: str, i: int) -> int:
    k = _skip_h(text, i)
    return k + 1 if _char(text, k) == "원" else i


def _finish(start: int, end: int, val: Decimal | None, explicit: bool, reason: str | None) -> MoneyToken:
    if reason is None and val is not None and val != val.to_integral_value():
        reason = AMBIG_NOT_INTEGER
    return MoneyToken(start, end, None if reason else int(val), explicit, reason)


def _scan_one(text: str, m: re.Match) -> MoneyToken | None:
    start = m.start()
    if _char(text, m.end()) == "," and _char(text, m.end() + 1).isdigit():
        return MoneyToken(start, m.end(), None, False, AMBIG_GROUPING)
    n, has_dec = _dec(m)
    k = _skip_h(text, m.end())
    unit = _char(text, k)
    if unit == "억":
        val = n * EOK
        end = k + 1
        k2 = _skip_h(text, end)
        m2 = _NUM_RE.match(text, k2) if _char(text, k2).isdigit() else None
        if m2 and _char(text, m2.end()) == "," and _char(text, m2.end() + 1).isdigit():
            return MoneyToken(start, m2.end(), None, True, AMBIG_GROUPING)
        if m2:
            sub, sub_dec = _dec(m2)
            k3 = _skip_h(text, m2.end())
            u2 = _char(text, k3)
            if u2 == "천":
                if sub_dec or not (1 <= sub <= 9):
                    return MoneyToken(start, k3 + 1, None, True, AMBIG_CHEON)
                val += sub * CHEONMAN
                end = k3 + 1
                k4 = _skip_h(text, end)
                if _char(text, k4) == "만":
                    end = k4 + 1
            elif u2 == "만":
                if sub_dec or sub > 9999:
                    return MoneyToken(start, k3 + 1, None, True, AMBIG_SUB_LARGE)
                val += sub * MAN
                end = k3 + 1
            elif u2 == "원":
                return MoneyToken(start, k3 + 1, None, True, AMBIG_SUB_WON)
            elif not _is_word_char(_char(text, m2.end())) and (u2 == "" or u2 in _SUB_BOUNDARY or k3 > m2.end()):
                if sub_dec:
                    return MoneyToken(start, m2.end(), None, True, AMBIG_DECIMAL)
                if sub > 9999:
                    return MoneyToken(start, m2.end(), None, True, AMBIG_SUB_LARGE)
                if sub < 100:
                    return MoneyToken(start, m2.end(), None, True, AMBIG_SUB_SMALL)
                val += sub * MAN
                end = m2.end()
        return _finish(start, _consume_won(text, end), val, True, None)
    if unit == "천":
        end = k + 1
        k2 = _skip_h(text, end)
        if _char(text, k2) == "만":
            end = k2 + 1
        elif _char(text, k2) == "원":
            return MoneyToken(start, k2 + 1, None, True, AMBIG_SUB_WON)
        if has_dec or not (1 <= n <= 9):
            return MoneyToken(start, end, None, True, AMBIG_CHEON)
        return _finish(start, _consume_won(text, end), n * CHEONMAN, True, None)
    if unit == "만":
        return _finish(start, _consume_won(text, k + 1), n * MAN, True, None)
    if unit == "원":
        return _finish(start, k + 1, n, True, None)
    nxt = _char(text, m.end())
    if _is_word_char(nxt) or nxt == "%":
        return None
    if has_dec:
        return MoneyToken(start, m.end(), None, False, AMBIG_DECIMAL)
    return _finish(start, m.end(), n * MAN, False, None)


def scan_money(text: str) -> list[MoneyToken]:
    tokens: list[MoneyToken] = []
    pos = 0
    for m in _NUM_RE.finditer(text):
        if m.start() < pos:
            continue
        tok = _scan_one(text, m)
        if tok is None:
            continue
        tokens.append(tok)
        pos = tok.end
    return tokens


def parse_krw_strict(text, bare_unit: int = MAN, bare_limit: int = 999_999) -> tuple[int | None, str | None]:
    if text is None:
        return None, None
    s = str(text).strip()
    if not s:
        return None, None
    if s.startswith("-"):
        return None, ERR_NEGATIVE
    tokens = scan_money(s)
    if not tokens:
        return None, ERR_UNPARSEABLE
    if len(tokens) > 1:
        return None, ERR_MULTIPLE
    tok = tokens[0]
    if tok.ambiguous:
        return None, tok.reason
    if s[: tok.start].strip() or s[tok.end :].strip():
        return None, ERR_UNPARSEABLE
    if not tok.explicit:
        raw = int(s.replace(",", ""))
        if raw > bare_limit:
            return None, AMBIG_BARE_LARGE
        return raw * bare_unit, None
    return tok.value, None


def parse_krw(text) -> int | None:
    value, _ = parse_krw_strict(text)
    return value


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


def format_krw_input(amount: int | None) -> str:
    if amount is None:
        return ""
    a = int(amount)
    if a == 0:
        return "0원"
    if a % MAN:
        return f"{a:,}원"
    eok, rem = divmod(a, EOK)
    man = rem // MAN
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    return " ".join(parts)


def format_eok(amount: int | None, digits: int = 2) -> str:
    if amount is None:
        return "-"
    return f"{amount / EOK:.{digits}f}억"


__all__ = [
    "EOK",
    "MAN",
    "MASK",
    "MoneyToken",
    "scan_money",
    "parse_krw_strict",
    "parse_krw",
    "parse_manwon",
    "format_krw",
    "format_krw_input",
    "format_eok",
    "InvalidOperation",
]
