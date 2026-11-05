from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .models import Transaction

COUNTRY_TZ: dict[str, str] = {
    "FR": "Europe/Paris",
    "GB": "Europe/London",
    "US": "America/New_York",
    "CA": "America/Toronto",
    "SG": "Asia/Singapore",
    "AE": "Asia/Dubai",
    "MA": "Africa/Casablanca",
    "CH": "Europe/Zurich",
    "PL": "Europe/Warsaw",
    "NL": "Europe/Amsterdam",
    "BE": "Europe/Brussels",
    "DE": "Europe/Berlin",
    "ES": "Europe/Madrid",
    "IT": "Europe/Rome",
    "KR": "Asia/Seoul",
    "JP": "Asia/Tokyo",
}

CITY_TZ: dict[tuple[str, str], str] = {
    ("US", "san francisco"): "America/Los_Angeles",
    ("US", "palo alto"): "America/Los_Angeles",
}

CITY_ALIASES: dict[str, str] = {
    "brussels": "bruxelles",
    "new york city": "new york",
    "nyc": "new york",
    "sf": "san francisco",
}


def normalize_city(city: str | None) -> str:
    s = (
        unicodedata.normalize("NFKD", city or "")
        .encode("ascii", "ignore")
        .decode()
        .casefold()
        .strip()
    )
    return CITY_ALIASES.get(s, s)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    s = str(value).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _as_aware(dt: datetime, tz: str) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo(tz))
    return dt


@dataclass
class Destination:
    city: str
    country: str
    frm: datetime
    to: datetime
    tz: str = "Asia/Seoul"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Destination":
        city = str(d.get("city", ""))
        country = str(d.get("country", "")).upper()
        tz = (
            d.get("tz")
            or CITY_TZ.get((country, normalize_city(city)))
            or COUNTRY_TZ.get(country, "Asia/Seoul")
        )
        return cls(
            city=city,
            country=country,
            frm=_parse_dt(d["from"]),
            to=_parse_dt(d["to"]),
            tz=str(tz),
        )


@dataclass
class Trip:
    id: str
    start: datetime
    end: datetime
    destinations: list[Destination] = field(default_factory=list)
    home_country: str = "KR"
    stay_type: str = "hotel"
    departure_at: datetime | None = None
    return_arrival_at: datetime | None = None
    extra_include: list[str] = field(default_factory=list)
    extra_exclude: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Trip":
        dests = [Destination.from_dict(x) for x in d.get("destinations", [])]
        return cls(
            id=str(d["id"]),
            start=_parse_dt(d["start"]),
            end=_parse_dt(d["end"]),
            destinations=dests,
            home_country=str(d.get("home_country", "KR")),
            stay_type=str(d.get("stay_type", "hotel")),
            departure_at=_parse_dt(d["departure_at"]) if d.get("departure_at") else None,
            return_arrival_at=_parse_dt(d["return_arrival_at"]) if d.get("return_arrival_at") else None,
            extra_include=[str(m).lower() for m in d.get("extra_include", [])],
            extra_exclude=[str(m).lower() for m in d.get("extra_exclude", [])],
        )

    @classmethod
    def load(cls, path: str | Path) -> "Trip":
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as e:
                raise RuntimeError("pyyaml required to load YAML trip files") from e
            return cls.from_dict(yaml.safe_load(text))
        return cls.from_dict(json.loads(text))

    def in_trip(self, txn: Transaction) -> bool:
        merchant = (txn.merchant or "").lower()
        if any(m in merchant for m in self.extra_exclude):
            return False
        if any(m in merchant for m in self.extra_include):
            return True
        start, end = self._bounds()
        return start <= _as_aware(txn.approved_at, "Asia/Seoul") <= end

    def _bounds(self) -> tuple[datetime, datetime]:
        tz = (
            self.destinations[0].tz
            if self.destinations
            else COUNTRY_TZ.get(self.home_country.upper(), "Asia/Seoul")
        )
        return _as_aware(self.start, tz), _as_aware(self.end, tz)

    def local_dt(self, dt: datetime) -> datetime:
        dt = _as_aware(dt, "Asia/Seoul")
        city, country = self.location_for(dt)
        tzname = None
        for d in self.destinations:
            if d.city == city and d.country.upper() == (country or "").upper():
                tzname = d.tz
                break
        if tzname is None:
            tzname = (
                self.destinations[0].tz
                if self.destinations
                else COUNTRY_TZ.get(self.home_country.upper(), "Asia/Seoul")
            )
        return dt.astimezone(ZoneInfo(tzname))

    def location_for(self, dt: datetime) -> tuple[str | None, str | None]:
        dt = _as_aware(dt, "Asia/Seoul")
        for d in self.destinations:
            frm = _as_aware(d.frm, d.tz)
            to = _as_aware(d.to, d.tz)
            if frm <= dt <= to:
                return d.city, d.country
        return None, None

    def nights(self) -> int:
        s = self.local_dt(self.start).date()
        e = self.local_dt(self.end).date()
        return max(0, (e - s).days)

    def eligible_meal_day(self, local_day: date) -> bool:
        start_day = self.local_dt(self.start).date()
        end_day = self.local_dt(self.end).date()
        if local_day == start_day:
            if self.departure_at is None:
                return True
            return self.departure_at.time() < time(17, 30)
        if local_day == end_day:
            if self.return_arrival_at is None:
                return True
            return self.return_arrival_at.time() > time(13, 0)
        return start_day < local_day < end_day
