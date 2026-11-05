import base64
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
import httpx
from tea.models import Transaction

_RETRYABLE = {429, 500, 502, 503, 504}


class MistralOcrClient:
    def __init__(
        self,
        api_key: str,
        http: httpx.Client,
        model: str = 'mistral-ocr-latest',
        sleep: Callable = None,
    ):
        self.api_key = api_key
        self.http = http
        self.model = model
        self.sleep = sleep
        self.base_url = 'https://api.mistral.ai/v1/ocr'

    def ocr(self, image_bytes: bytes) -> str:
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        body = {
            'model': self.model,
            'document': {
                'type': 'image_url',
                'image_url': f'data:image/png;base64,{image_b64}',
            },
        }
        last: Optional[httpx.Response] = None
        for attempt in range(3):
            response = self.http.post(
                self.base_url, headers=headers, json=body, timeout=60.0)
            if response.status_code in _RETRYABLE and attempt < 2:
                if self.sleep:
                    self.sleep(0.5 * (2 ** attempt))
                continue
            last = response
            break
        if last is not None and last.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"OCR request failed: {last.status_code}",
                request=last.request,
                response=last,
            )
        data = last.json()
        return '\n'.join(p['markdown'] for p in data['pages'])


def _normalize_number(raw: str) -> Decimal:
    raw = raw.strip().replace(' ', '')
    if ',' in raw and '.' not in raw:
        head, _, tail = raw.rpartition(',')
        if len(tail.replace(',', '')) == 2 and head:
            raw = raw.replace(',', '.')
    raw = raw.replace(',', '').replace('원', '').replace('KRW', '')
    return Decimal(raw)


def _candidates(text: str) -> list[Decimal]:
    out: list[Decimal] = []
    for m in re.finditer(r'\d[\d\., ]*', text):
        try:
            out.append(_normalize_number(m.group()))
        except InvalidOperation:
            continue
    return out


def _extract_amount(text: str, txn: Transaction) -> bool:
    targets = [txn.amount]
    if txn.amount_krw is not None:
        targets.append(txn.amount_krw)
    targets = [t.quantize(Decimal('0.01')) for t in targets]
    for cand in _candidates(text):
        try:
            c = cand.quantize(Decimal('0.01'))
        except InvalidOperation:
            continue
        if c in targets:
            return True
    return False


def _check_merchant(text: str, merchant: str) -> bool:
    ocr_fold = text.casefold()
    merchant_fold = merchant.casefold()
    ocr_tokens = set(t for t in re.findall(r'\w+', ocr_fold) if len(t) >= 2)
    merchant_tokens = [t for t in re.findall(r'\w+', merchant_fold) if len(t) >= 2]
    if not merchant_tokens:
        return False
    common = sum(1 for t in merchant_tokens if t in ocr_tokens)
    if common / len(merchant_tokens) >= 0.6:
        return True
    compact_merchant = re.sub(r'\s+', '', merchant_fold)
    compact_ocr = re.sub(r'\s+', '', ocr_fold)
    return compact_merchant in compact_ocr


def ocr_check(png_path: Path, txn: Transaction, client: MistralOcrClient) -> dict:
    ocr_text = client.ocr(png_path.read_bytes())
    found_amount = _extract_amount(ocr_text, txn)
    found_merchant = _check_merchant(ocr_text, txn.merchant)
    notes = []
    if not found_amount:
        notes.append('Amount not found or mismatch')
    if not found_merchant:
        notes.append('Merchant not found or mismatch')
    return {
        'ok': found_amount and found_merchant,
        'found_amount': found_amount,
        'found_merchant': found_merchant,
        'notes': '; '.join(notes),
    }
