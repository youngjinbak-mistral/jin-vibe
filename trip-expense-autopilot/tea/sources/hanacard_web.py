from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tea.models import Transaction, AuthRequired, CaptchaRequired, SelectorDrift

SEOUL = ZoneInfo("Asia/Seoul")
_RENDERED_JS = (
    "el => { for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const s = getComputedStyle(n); "
    "if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false; } "
    "return el.getClientRects().length > 0; }"
)


def _parse_amount(text: str | None) -> Decimal:
    if not text:
        return Decimal("0")
    cleaned = re.sub(r"[^\d.\-]", "", str(text).strip())
    if not cleaned:
        return Decimal("0")
    return Decimal(cleaned)


def _last4(card_no: str | None) -> str:
    digits = "".join(ch for ch in str(card_no or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits


class HanaCardWeb:
    def __init__(
        self,
        selectors_path: str | Path,
        state_path: str | Path = "~/.tea/hana_state.json",
    ) -> None:
        self.selectors_path = Path(selectors_path)
        with self.selectors_path.open(encoding="utf-8") as f:
            self.selectors: dict[str, Any] = json.load(f)
        self.state_path = Path(state_path).expanduser()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _sel(self, key: str) -> str:
        return self.selectors[key]

    def _cell_sel(self, key: str) -> str:
        return self.selectors["cells"][key]

    def _save_state(self, page: Any) -> None:
        state = page.context.storage_state()
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        os.chmod(self.state_path, 0o600)

    @staticmethod
    def _visible(page: Any, selector: str) -> bool:
        loc = page.locator(selector)
        for i in range(loc.count()):
            el = loc.nth(i)
            if el.is_visible() or el.evaluate(_RENDERED_JS):
                return True
        return False

    def _check_blockers(self, page: Any) -> None:
        if self._visible(page, self._sel("captcha")):
            raise CaptchaRequired("captcha detected on Hana Card page")
        if self._visible(page, self._sel("session_expired")):
            raise AuthRequired("Hana Card session expired")

    def _snapshot(self, page: Any) -> str:
        return page.evaluate(
            "([rowSel, emptySel]) => { const t = [...document.querySelectorAll(rowSel)].map(r => r.innerText).join('|'); "
            "const e = emptySel ? [...document.querySelectorAll(emptySel.split(',')[0])].some(x => x.offsetParent !== null) : false; return t + '#' + e; }",
            [self._sel("row"), self.selectors.get("empty_marker", "")],
        )

    @staticmethod
    def _click(page: Any, target: Any) -> None:
        loc = page.locator(target).first if isinstance(target, str) else target.first
        if loc.is_visible():
            loc.click()
        elif loc.evaluate(_RENDERED_JS):
            loc.dispatch_event("click")
        else:
            loc.click()

    def _click_and_wait(self, page: Any, selector: str, timeout_ms: int = 15000) -> None:
        before = self._snapshot(page)
        self._click(page, selector)
        page.wait_for_load_state("networkidle")
        deadline = timeout_ms
        while deadline > 0:
            if self._snapshot(page) != before:
                page.wait_for_timeout(100)
                return
            page.wait_for_timeout(100)
            deadline -= 100

    def _search(self, page: Any, start_s: str, end_s: str) -> None:
        page.fill(self._sel("date_from"), start_s)
        page.fill(self._sel("date_to"), end_s)
        self._click_and_wait(page, self._sel("search_button"))

    def _next_page(self, page: Any) -> bool:
        next_btn = page.locator(self._sel("next_page"))
        disabled_attr = self.selectors.get("next_page_disabled_attr", "disabled")
        if next_btn.count() == 0 or next_btn.first.get_attribute(disabled_attr) is not None:
            return False
        self._click_and_wait(page, self._sel("next_page"))
        return True

    def login(self, page: Any, timeout_s: int = 300) -> None:
        page.goto(self._sel("login_url"))
        deadline = datetime.now().timestamp() + timeout_s
        while datetime.now().timestamp() < deadline:
            self._check_blockers(page)
            if self._visible(page, self._sel("logged_in")):
                self._save_state(page)
                return
            page.wait_for_timeout(1000)
        raise AuthRequired("login not completed within timeout")

    def ensure_session(self, page: Any) -> None:
        if self.state_path.exists():
            try:
                page.context.add_cookies(
                    json.loads(self.state_path.read_text(encoding="utf-8")).get(
                        "cookies", []
                    )
                )
            except (OSError, ValueError):
                pass
        page.goto(self._sel("history_url"))
        page.wait_for_load_state("networkidle")
        self._check_blockers(page)
        if not self._visible(page, self._sel("logged_in")):
            raise AuthRequired("not logged in to Hana Card")

    def list_transactions(self, page: Any, start: Any, end: Any) -> list[Transaction]:
        self.ensure_session(page)
        self._search(page, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))

        txns: list[Transaction] = []
        while True:
            self._check_blockers(page)
            rows = page.locator(self._sel("row"))
            count = rows.count()
            if count == 0:
                if "empty_marker" not in self.selectors or not self._visible(page, self._sel("empty_marker")):
                    raise SelectorDrift(
                        f"selector {self._sel('row')!r} matched 0 rows and no empty marker present"
                    )
                return txns
            for i in range(count):
                row = rows.nth(i)
                try:
                    date_text = row.locator(self._cell_sel("date")).inner_text()
                    time_text = row.locator(self._cell_sel("time")).inner_text()
                    merchant = row.locator(self._cell_sel("merchant")).inner_text().strip()
                    amount = _parse_amount(row.locator(self._cell_sel("amount")).inner_text())
                    currency = (
                        row.locator(self._cell_sel("currency")).inner_text().strip().upper()
                    ) or "KRW"
                    amount_krw_text = row.locator(self._cell_sel("amount_krw")).inner_text()
                    approval_no = row.locator(self._cell_sel("approval_no")).inner_text().strip()
                    card_no = row.locator(self._cell_sel("card_no")).inner_text()
                    status_text = row.locator(self._cell_sel("status")).inner_text().strip()
                    country_text = row.locator(self._cell_sel("country")).inner_text().strip()
                except Exception as exc:
                    raise SelectorDrift(f"failed to read row cells: {exc}") from exc

                digits = re.sub(r"\D", "", date_text)
                time_digits = re.sub(r"\D", "", time_text) or "000000"
                if len(digits) == 8:
                    dt = datetime.strptime(digits + time_digits.zfill(6), "%Y%m%d%H%M%S")
                else:
                    dt = datetime.strptime(digits + time_digits.zfill(6), "%y%m%d%H%M%S")
                approved_at = dt.replace(tzinfo=SEOUL)

                status = "approved"
                if "부분" in status_text:
                    status = "partial_cancel"
                elif "취소" in status_text or "cancel" in status_text.lower():
                    status = "cancelled"
                if status == "cancelled":
                    amount = -abs(amount)

                amount_krw = _parse_amount(amount_krw_text) if amount_krw_text.strip() else None
                card_last4 = _last4(card_no)
                country = country_text.upper()[:2] if len(country_text) >= 2 else None

                txn_id_source = (
                    f"{card_last4}|{approval_no}|{approved_at.isoformat()}|{amount}|{currency}"
                )
                txn_id = hashlib.sha1(txn_id_source.encode()).hexdigest()[:16]

                txns.append(
                    Transaction(
                        txn_id=txn_id,
                        approved_at=approved_at,
                        merchant=merchant,
                        amount=amount,
                        currency=currency,
                        amount_krw=amount_krw,
                        card_last4=card_last4,
                        approval_no=approval_no,
                        status=status,
                        country=country,
                        mcc_category=None,
                        raw={"source": "hanacard_web"},
                    )
                )
            if not self._next_page(page):
                break
        return txns

    def _find_detail_link(self, page: Any, txn: Transaction) -> Any:
        link_sel = self._sel("detail_link_template").format(approval_no=txn.approval_no)
        link = page.locator(link_sel)
        if link.count() > 0:
            return link
        day = txn.approved_at.astimezone(SEOUL).strftime("%Y%m%d")
        self._search(page, day, day)
        for _ in range(50):
            self._check_blockers(page)
            link = page.locator(link_sel)
            if link.count() > 0:
                return link
            if not self._next_page(page):
                break
        raise SelectorDrift(f"detail link not found for approval {txn.approval_no}")

    def screenshot_transaction(self, page: Any, txn: Transaction, out_dir: str | Path) -> Path:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        self._check_blockers(page)
        link = self._find_detail_link(page, txn)
        self._click(page, link)
        panel = page.locator(self._sel("detail_panel"))
        panel.wait_for(state="visible", timeout=10000)
        for mask_sel in self.selectors.get("mask", []):
            mask_loc = page.locator(mask_sel)
            for i in range(mask_loc.count()):
                mask_loc.nth(i).evaluate(
                    "el => { el.style.color = 'transparent';"
                    " el.style.textShadow = 'none'; el.style.background = 'black'; }"
                )
        path = out / f"{txn.txn_id}.png"
        panel.screenshot(path=str(path))
        close_sel = self._sel("detail_close")
        close = page.locator(close_sel)
        if close.count() > 0 and close.first.evaluate(_RENDERED_JS):
            self._click(page, close)
        return path
