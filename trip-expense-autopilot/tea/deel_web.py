import json
from pathlib import Path
from typing import Optional
from playwright.sync_api import Page, TimeoutError as PwTimeoutError
from tea.models import AuthRequired
from tea.ledger import Ledger
from tea.sources.hanacard_web import _RENDERED_JS


class DeelFormError(Exception):
    def __init__(self, message: str, rejected: bool = True) -> None:
        super().__init__(message)
        self.rejected = rejected


class DeelWeb:
    def __init__(self, selectors_path: Path, ledger: Ledger, out_dir: str | Path = '~/.tea/deel'):
        self.selectors = json.loads(Path(selectors_path).read_text())
        self.ledger = ledger
        self.out_dir = Path(out_dir).expanduser()
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def prepare_expense(
        self,
        page: Page,
        item: dict,
        screenshot: Path,
        approve: bool = False,
    ) -> str:
        txn_id = item['txn_id']
        status = self.ledger.get(txn_id)

        if status == 'submitted':
            return 'skipped-duplicate'
        if status == 'submitting':
            return 'needs-verification'

        if item['policy_status'] == 'FAIL':
            self.ledger.set(txn_id, 'skipped')
            return 'skipped-fail'

        if not Path(screenshot).is_file():
            return 'skipped-no-evidence'

        self._fill_form(page, item, screenshot)

        if approve:
            self._check_session(page)
            self.ledger.set(txn_id, 'submitting')
            page.click(self.selectors['submit'])
            try:
                ref = self._wait_confirmation(page)
            except DeelFormError as exc:
                if exc.rejected:
                    self.ledger.resolve_submitting(txn_id, submitted=False)
                raise
            self.ledger.set(txn_id, 'submitted', ref)
            return 'submitted'

        form_png = self.out_dir / f"{txn_id}.deel_form.png"
        page.screenshot(path=str(form_png), full_page=True)
        self.ledger.set(txn_id, 'drafted')
        return 'drafted'

    def _check_session(self, page: Page) -> None:
        loc = page.locator(self.selectors['session_expired'])
        for i in range(loc.count()):
            el = loc.nth(i)
            if el.is_visible() or el.evaluate(_RENDERED_JS):
                raise AuthRequired("Session expired")

    def _fill_form(self, page: Page, item: dict, screenshot: Path) -> None:
        page.goto(self.selectors['expenses_url'])
        self._check_session(page)

        page.click(self.selectors['add_expense'])
        self._check_session(page)

        category = self.selectors['category_map'].get(
            item['category'], self.selectors['category_default'])
        self._choose(page, 'category', category)

        self._check_session(page)
        page.fill(self.selectors['amount'], f"{item['amount']:.2f}")

        self._check_session(page)
        self._choose(page, 'currency', item['currency'])

        self._check_session(page)
        page.fill(self.selectors['date'], item['date'])

        description = f"{item['merchant']} — {item['trip_id']} — {item['policy_reason']} [tea:{item['txn_id']}]"
        page.fill(self.selectors['description'], description)

        page.set_input_files(self.selectors['file_input'], screenshot)

    def _choose(self, page: Page, kind: str, value: str) -> None:
        select_kind = self.selectors.get(f'{kind}_select_kind', 'native')
        select = self.selectors[f'{kind}_select']
        if select_kind == 'native':
            page.select_option(select, label=value)
        else:
            page.click(select)
            option = self.selectors[f'{kind}_option_template'].format(value=value)
            page.click(option)

    def _wait_confirmation(self, page: Page) -> str:
        try:
            page.wait_for_selector(
                self.selectors['confirmation_ref'], timeout=30000)
            return (page.text_content(self.selectors['confirmation_ref']) or '').strip()
        except PwTimeoutError:
            error = page.text_content(self.selectors['form_error'])
            if error:
                raise DeelFormError(error.strip())
            raise DeelFormError("No confirmation or error shown after submit", rejected=False)
