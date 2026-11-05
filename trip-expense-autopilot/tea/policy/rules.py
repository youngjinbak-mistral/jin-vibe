from __future__ import annotations

from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from ..fx import FxRates
from ..models import PolicyResult, Transaction
from ..trip import COUNTRY_TZ, Trip, normalize_city

CENT = Decimal("0.01")

EU_EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PT", "RO", "SK", "SI", "ES",
    "SE", "IS", "LI", "NO",
}

CITY_HOTEL_CAPS: dict[tuple[str, str], tuple[Decimal, str]] = {
    ("london", "GB"): (Decimal("260"), "GBP"),
    ("paris", "FR"): (Decimal("230"), "EUR"),
    ("bruxelles", "BE"): (Decimal("250"), "EUR"),
    ("amsterdam", "NL"): (Decimal("250"), "EUR"),
    ("new york", "US"): (Decimal("350"), "USD"),
    ("san francisco", "US"): (Decimal("475"), "USD"),
    ("palo alto", "US"): (Decimal("475"), "USD"),
    ("toronto", "CA"): (Decimal("350"), "CAD"),
    ("montreal", "CA"): (Decimal("350"), "CAD"),
}

COUNTRY_HOTEL_CAPS: dict[str, tuple[Decimal, str]] = {
    "GB": (Decimal("150"), "GBP"),
    "AE": (Decimal("1000"), "AED"),
    "MA": (Decimal("1500"), "MAD"),
    "US": (Decimal("280"), "USD"),
    "CA": (Decimal("280"), "CAD"),
    "SG": (Decimal("400"), "SGD"),
}

REGION_HOTEL_CAPS: dict[str, tuple[Decimal, str]] = {
    "Europe": (Decimal("180"), "EUR"),
}

CITY_MEAL_CAPS: dict[tuple[str, str], tuple[Decimal, str]] = {
    ("new york", "US"): (Decimal("100"), "USD"),
    ("san francisco", "US"): (Decimal("100"), "USD"),
    ("toronto", "CA"): (Decimal("100"), "CAD"),
    ("montreal", "CA"): (Decimal("100"), "CAD"),
}

COUNTRY_MEAL_CAPS: dict[str, tuple[Decimal, str]] = {
    "GB": (Decimal("50"), "GBP"),
    "MA": (Decimal("320"), "MAD"),
    "CH": (Decimal("50"), "CHF"),
    "PL": (Decimal("150"), "PLN"),
    "US": (Decimal("75"), "USD"),
    "CA": (Decimal("75"), "CAD"),
    "SG": (Decimal("55"), "SGD"),
}

REGION_MEAL_CAPS: dict[str, tuple[Decimal, str]] = {
    "Europe": (Decimal("45"), "EUR"),
}

GIFT_CAPS: dict[str, tuple[Decimal, Decimal]] = {
    "EUR": (Decimal("50"), Decimal("300")),
    "GBP": (Decimal("45"), Decimal("260")),
    "USD": (Decimal("60"), Decimal("355")),
    "SGD": (Decimal("75"), Decimal("440")),
}

GIFT_KEYWORDS = ("gift", "선물")

PRE_TRIP_CATEGORIES = ("flight", "train", "hotel", "visa")


def _region(country: str | None) -> str | None:
    if not country:
        return None
    c = country.upper()
    if c in ("GB", "MA", "CH", "PL", "AE", "US", "CA", "SG"):
        return c
    if c in EU_EEA:
        return "Europe"
    return None


def hotel_cap(city: str | None, country: str | None) -> tuple[Decimal, str] | None:
    if city and country:
        key = (normalize_city(city), country.upper())
        if key in CITY_HOTEL_CAPS:
            return CITY_HOTEL_CAPS[key]
    if country:
        c = country.upper()
        if c in COUNTRY_HOTEL_CAPS:
            return COUNTRY_HOTEL_CAPS[c]
        r = _region(c)
        if r and r in REGION_HOTEL_CAPS:
            return REGION_HOTEL_CAPS[r]
    return None


def meal_cap(city: str | None, country: str | None, long_term: bool = False) -> tuple[Decimal, str] | None:
    cap: tuple[Decimal, str] | None = None
    if city and country:
        key = (normalize_city(city), country.upper())
        if key in CITY_MEAL_CAPS:
            cap = CITY_MEAL_CAPS[key]
    if cap is None and country:
        c = country.upper()
        if c in COUNTRY_MEAL_CAPS:
            cap = COUNTRY_MEAL_CAPS[c]
        else:
            r = _region(c)
            if r and r in REGION_MEAL_CAPS:
                cap = REGION_MEAL_CAPS[r]
    if cap is None:
        return None
    amount, ccy = cap
    if long_term:
        amount = amount * Decimal("0.5")
    return amount, ccy


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _to_txn_ccy(amount: Decimal, cap_ccy: str, txn_ccy: str, fx: FxRates, day: date) -> Decimal:
    if cap_ccy == txn_ccy:
        return amount
    return _q(amount * fx.rate(day, cap_ccy, txn_ccy))


def _nights_per_city(trip: Trip) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for d in trip.destinations:
        tz = ZoneInfo(d.tz)
        frm = d.frm if d.frm.tzinfo else d.frm.replace(tzinfo=tz)
        to = d.to if d.to.tzinfo else d.to.replace(tzinfo=tz)
        n = max(1, (to.astimezone(tz).date() - frm.astimezone(tz).date()).days)
        key = normalize_city(d.city)
        counts[key] += n
    return dict(counts)


def _trip_bounds(trip: Trip) -> tuple[datetime, datetime]:
    tz = (
        trip.destinations[0].tz
        if trip.destinations
        else COUNTRY_TZ.get(trip.home_country.upper(), "Asia/Seoul")
    )
    s = trip.start if trip.start.tzinfo else trip.start.replace(tzinfo=ZoneInfo(tz))
    e = trip.end if trip.end.tzinfo else trip.end.replace(tzinfo=ZoneInfo(tz))
    return s, e


def _loc(trip: Trip, txn: Transaction) -> tuple[str | None, str | None]:
    city, country = trip.location_for(txn.approved_at)
    if city is None and trip.destinations:
        start, end = _trip_bounds(trip)
        if txn.approved_at < start:
            d = trip.destinations[0]
            return d.city, d.country
        if txn.approved_at > end:
            d = trip.destinations[-1]
            return d.city, d.country
    return city, country


def evaluate(
    txns: list[Transaction],
    trip: Trip,
    fx: FxRates,
    categories: dict[str, str],
) -> dict[str, PolicyResult]:
    results: dict[str, PolicyResult] = {}
    long_term = trip.stay_type == "long_term"
    nights_city = _nights_per_city(trip)
    remaining: dict[date, Decimal] = {}
    cap_ccy_day: dict[date, str] = {}
    start, end = _trip_bounds(trip)

    ordered = sorted((t for t in txns if t.status != "cancelled"), key=lambda t: t.approved_at)
    for txn in ordered:
        cat = categories.get(txn.txn_id, "other")

        if txn.amount < 0:
            results[txn.txn_id] = PolicyResult(
                status="PASS", category=cat, reasons=["refund"],
                cap=None, cap_currency=None, reimbursable=_q(txn.amount),
            )
            continue

        city, country = _loc(trip, txn)
        local_day = trip.local_dt(txn.approved_at).date()
        day = local_day
        res: PolicyResult

        if cat == "insurance":
            res = PolicyResult(
                status="FAIL", category=cat, reasons=["insurance covered by company"],
                cap=None, cap_currency=None, reimbursable=Decimal("0.00"),
            )
        elif cat == "visa":
            res = PolicyResult(
                status="PASS", category=cat, reasons=["visa/ESTA/ETA reimbursable"],
                cap=None, cap_currency=None, reimbursable=_q(txn.amount),
            )
        elif cat in ("flight", "train"):
            res = PolicyResult(
                status="FLAG", category=cat, reasons=["verify class & booking channel"],
                cap=None, cap_currency=None, reimbursable=_q(txn.amount),
            )
        elif cat == "taxi":
            res = PolicyResult(
                status="PASS", category=cat, reasons=["justify if public transport available"],
                cap=None, cap_currency=None, reimbursable=_q(txn.amount),
            )
        elif cat == "public_transport":
            res = PolicyResult(
                status="PASS", category=cat, reasons=[],
                cap=None, cap_currency=None, reimbursable=_q(txn.amount),
            )
        elif cat == "mileage":
            res = PolicyResult(
                status="FLAG", category=cat, reasons=["attach map screenshot"],
                cap=None, cap_currency=None, reimbursable=_q(txn.amount),
            )
        elif cat == "equipment":
            res = PolicyResult(
                status="FLAG", category=cat, reasons=["not a travel expense; remote budget"],
                cap=None, cap_currency=None, reimbursable=Decimal("0.00"),
            )
        elif cat == "other":
            res = PolicyResult(
                status="FLAG", category=cat, reasons=["unclassified: likely personal, confirm business purpose"],
                cap=None, cap_currency=None, reimbursable=Decimal("0.00"),
            )
        elif cat == "hotel":
            cap = hotel_cap(city, country)
            if cap is None:
                res = PolicyResult(
                    status="FLAG", category=cat, reasons=["no cap defined"],
                    cap=None, cap_currency=None, reimbursable=_q(txn.amount),
                )
            else:
                cap_amt, cap_ccy = cap
                n = nights_city.get(normalize_city(city), 1)
                per_night = _q(txn.amount / Decimal(n))
                per_night_cap_ccy = per_night if txn.currency == cap_ccy else _q(
                    per_night * fx.rate(day, txn.currency, cap_ccy)
                )
                cap_in_txn = _to_txn_ccy(cap_amt, cap_ccy, txn.currency, fx, day)
                reimb = min(_q(txn.amount), _q(cap_in_txn * Decimal(n)))
                if per_night_cap_ccy > cap_amt and trip.nights() > 10:
                    res = PolicyResult(
                        status="FAIL", category=cat,
                        reasons=["hotel over cap and stay > 10 nights: no out of policy exceptions > 10 days"],
                        cap=cap_amt, cap_currency=cap_ccy, reimbursable=Decimal("0.00"),
                    )
                elif per_night_cap_ccy > cap_amt:
                    res = PolicyResult(
                        status="FLAG", category=cat,
                        reasons=[f"hotel over nightly cap ({per_night_cap_ccy} {cap_ccy} > {cap_amt} {cap_ccy})"],
                        cap=cap_amt, cap_currency=cap_ccy, reimbursable=_q(reimb),
                    )
                else:
                    res = PolicyResult(
                        status="PASS", category=cat, reasons=[],
                        cap=cap_amt, cap_currency=cap_ccy, reimbursable=_q(txn.amount),
                    )
        elif cat == "meal":
            if not trip.eligible_meal_day(local_day):
                res = PolicyResult(
                    status="FLAG", category=cat, reasons=["day not eligible"],
                    cap=None, cap_currency=None, reimbursable=Decimal("0.00"),
                )
            else:
                cap = meal_cap(city, country, long_term)
                if cap is None:
                    res = PolicyResult(
                        status="FLAG", category=cat, reasons=["no cap defined"],
                        cap=None, cap_currency=None, reimbursable=_q(txn.amount),
                    )
                else:
                    cap_amt, cap_ccy = cap
                    if day not in remaining:
                        remaining[day] = cap_amt
                        cap_ccy_day[day] = cap_ccy
                    rem_txn = _to_txn_ccy(remaining[day], cap_ccy_day[day], txn.currency, fx, day)
                    if rem_txn <= 0:
                        res = PolicyResult(
                            status="FLAG", category=cat,
                            reasons=[f"daily meal cap exhausted ({cap_amt} {cap_ccy})"],
                            cap=cap_amt, cap_currency=cap_ccy, reimbursable=Decimal("0.00"),
                        )
                    else:
                        reimb = min(_q(txn.amount), rem_txn)
                        remaining[day] = _q(remaining[day] - _to_txn_ccy(reimb, txn.currency, cap_ccy_day[day], fx, day))
                        if _q(txn.amount) > rem_txn:
                            res = PolicyResult(
                                status="FLAG", category=cat,
                                reasons=[f"meal over daily cap ({cap_amt} {cap_ccy})"],
                                cap=cap_amt, cap_currency=cap_ccy, reimbursable=_q(reimb),
                            )
                        else:
                            res = PolicyResult(
                                status="PASS", category=cat, reasons=[],
                                cap=cap_amt, cap_currency=cap_ccy, reimbursable=_q(txn.amount),
                            )
        elif cat == "gift":
            merch = (txn.merchant or "").lower()
            is_gift = any(k in merch for k in GIFT_KEYWORDS)
            cap_ccy = txn.currency if txn.currency in GIFT_CAPS else ("EUR" if _region(country) == "Europe" else txn.currency)
            limits = GIFT_CAPS.get(cap_ccy)
            if limits is None:
                res = PolicyResult(
                    status="FLAG", category=cat, reasons=["no cap defined"],
                    cap=None, cap_currency=None, reimbursable=_q(txn.amount),
                )
            else:
                short, long_lim = limits
                lim = long_lim if trip.nights() >= 7 else short
                lim_txn = _to_txn_ccy(lim, cap_ccy, txn.currency, fx, day) if is_gift else _q(txn.amount)
                if is_gift and _q(txn.amount) > lim_txn:
                    res = PolicyResult(
                        status="FLAG", category=cat,
                        reasons=[f"gift over cap ({lim} {cap_ccy})"],
                        cap=lim, cap_currency=cap_ccy, reimbursable=_q(lim_txn),
                    )
                else:
                    res = PolicyResult(
                        status="PASS", category=cat, reasons=[],
                        cap=lim if is_gift else None,
                        cap_currency=cap_ccy if is_gift else None,
                        reimbursable=_q(txn.amount),
                    )
        elif cat == "car_rental":
            if (country or "").upper() == "US":
                cap_amt, cap_ccy = Decimal("75"), "USD"
                days = nights_city.get(normalize_city(city), 1)
                per_day = _q(txn.amount / Decimal(days)) if txn.currency == cap_ccy else _q(
                    (txn.amount / Decimal(days)) * fx.rate(day, txn.currency, cap_ccy)
                )
                cap_in_txn = _to_txn_ccy(cap_amt, cap_ccy, txn.currency, fx, day)
                if per_day > cap_amt:
                    res = PolicyResult(
                        status="FLAG", category=cat,
                        reasons=[f"car rental over daily cap ({cap_amt} {cap_ccy})"],
                        cap=cap_amt, cap_currency=cap_ccy,
                        reimbursable=min(_q(txn.amount), _q(cap_in_txn * Decimal(days))),
                    )
                elif days <= 1:
                    res = PolicyResult(
                        status="FLAG", category=cat, reasons=["verify rental length"],
                        cap=cap_amt, cap_currency=cap_ccy, reimbursable=_q(txn.amount),
                    )
                else:
                    res = PolicyResult(
                        status="PASS", category=cat, reasons=[],
                        cap=cap_amt, cap_currency=cap_ccy, reimbursable=_q(txn.amount),
                    )
            else:
                res = PolicyResult(
                    status="FLAG", category=cat, reasons=["local law"],
                    cap=None, cap_currency=None, reimbursable=_q(txn.amount),
                )
        else:
            res = PolicyResult(
                status="PASS", category=cat, reasons=[],
                cap=None, cap_currency=None, reimbursable=_q(txn.amount),
            )

        pre_trip = txn.approved_at < start
        outside = pre_trip or txn.approved_at > end
        if outside:
            if pre_trip and cat in PRE_TRIP_CATEGORIES:
                res.reasons.append("pre-trip booking")
            else:
                res.status = "FLAG"
                res.reasons.append("outside trip dates")
                res.reimbursable = Decimal("0.00")

        results[txn.txn_id] = res

    return results
