from __future__ import annotations

import json
import time
import urllib.request
from decimal import Decimal
from pathlib import Path


class FxError(Exception):
    pass


class FxRates:
    def rate(self, date, from_ccy: str, to_ccy: str) -> Decimal:
        raise NotImplementedError


class StaticFx(FxRates):
    def __init__(self, table: dict[tuple[str, str], Decimal]):
        self.table = {k: Decimal(str(v)) for k, v in table.items()}

    def rate(self, date, from_ccy: str, to_ccy: str) -> Decimal:
        from_ccy = from_ccy.upper()
        to_ccy = to_ccy.upper()
        if from_ccy == to_ccy:
            return Decimal("1")
        key = (from_ccy, to_ccy)
        if key in self.table:
            return self.table[key]
        inv = (to_ccy, from_ccy)
        if inv in self.table:
            return Decimal("1") / self.table[inv]
        raise FxError(f"no rate {from_ccy}->{to_ccy}")


class FrankfurterFx(FxRates):
    BASE = "https://api.frankfurter.app"

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, day: str, base: str) -> Path:
        return self.cache_dir / f"{day}_{base}.json"

    def _fetch(self, day: str, base: str) -> dict:
        url = f"{self.BASE}/{day}?from={base}"
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    def rate(self, date, from_ccy: str, to_ccy: str) -> Decimal:
        from_ccy = from_ccy.upper()
        to_ccy = to_ccy.upper()
        if from_ccy == to_ccy:
            return Decimal("1")
        day = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
        path = self._cache_path(day, from_ccy)
        data = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = None
        if data is None:
            for attempt in range(3):
                try:
                    data = self._fetch(day, from_ccy)
                    break
                except Exception:
                    if attempt == 2:
                        raise FxError(f"fx fetch failed for {day} {from_ccy}")
                    time.sleep(1 + attempt)
            path.write_text(json.dumps(data), encoding="utf-8")
        rates = data.get("rates", {})
        if to_ccy not in rates:
            raise FxError(f"no rate {from_ccy}->{to_ccy} on {day}")
        return Decimal(str(rates[to_ccy]))
