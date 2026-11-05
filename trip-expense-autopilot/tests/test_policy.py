from decimal import Decimal

import pytest

from conftest import make_txn
from tea.fx import StaticFx
from tea.policy.rules import evaluate, hotel_cap, meal_cap
from tea.trip import Trip

NOFX = StaticFx({})


def _trip(**over):
    d = {
        "id": "T-1",
        "start": "2026-10-12T10:00:00+09:00",
        "end": "2026-10-17T18:00:00+02:00",
        "departure_at": "2026-10-12T10:00:00+09:00",
        "return_arrival_at": "2026-10-18T14:30:00+09:00",
        "destinations": [
            {"city": "Paris", "country": "FR",
             "from": "2026-10-12T00:00:00+02:00", "to": "2026-10-17T23:59:00+02:00"}
        ],
    }
    d.update(over)
    return Trip.from_dict(d)


def _run(trip, items, fx=NOFX):
    txns = [t for t, _ in items]
    cats = {t.txn_id: c for t, c in items}
    return evaluate(txns, trip, fx, cats), txns


def _txn(merchant, amount, ccy, when, n, **kw):
    return make_txn(merchant, Decimal(str(amount)), ccy, when, approval_no=f"A{n:05d}", **kw)


def test_hotel_cap_london_is_gbp_260():
    assert hotel_cap("London", "GB") == (Decimal("260"), "GBP")


def test_hotel_cap_uk_global_manchester_is_gbp_150():
    assert hotel_cap("Manchester", "GB") == (Decimal("150"), "GBP")


def test_hotel_cap_paris_is_eur_230():
    assert hotel_cap("Paris", "FR") == (Decimal("230"), "EUR")


def test_hotel_cap_europe_global_lyon_is_eur_180():
    assert hotel_cap("Lyon", "FR") == (Decimal("180"), "EUR")


def test_hotel_cap_brussels_alias_matches_bruxelles_250():
    assert hotel_cap("Brussels", "BE") == (Decimal("250"), "EUR")


def test_hotel_cap_montreal_with_accent_is_cad_350():
    assert hotel_cap("Montréal", "CA") == (Decimal("350"), "CAD")


@pytest.mark.parametrize("city", ["NYC", "New York City", "New York"])
def test_hotel_cap_nyc_aliases_are_usd_350(city):
    assert hotel_cap(city, "US") == (Decimal("350"), "USD")


def test_hotel_cap_san_francisco_is_usd_475():
    assert hotel_cap("San Francisco", "US") == (Decimal("475"), "USD")


def test_hotel_cap_singapore_is_sgd_400():
    assert hotel_cap("Singapore", "SG") == (Decimal("400"), "SGD")


def test_meal_cap_switzerland_is_chf_50():
    assert meal_cap("Zurich", "CH") == (Decimal("50"), "CHF")


def test_meal_cap_poland_is_pln_150():
    assert meal_cap("Warsaw", "PL") == (Decimal("150"), "PLN")


def test_meal_cap_singapore_is_sgd_55():
    assert meal_cap("Singapore", "SG") == (Decimal("55"), "SGD")


def test_meal_cap_long_term_halves_paris_to_22_50():
    assert meal_cap("Paris", "FR", long_term=True) == (Decimal("22.50"), "EUR")


def test_hotel_multi_night_within_cap_passes(paris_trip):
    t = _txn("Hotel Lutetia", "1050", "EUR", "2026-10-16T09:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "hotel")])
    assert res[t.txn_id].status == "PASS"


def test_hotel_multi_night_over_cap_flags_with_capped_reimbursable(paris_trip):
    t = _txn("Hotel Lutetia", "1300", "EUR", "2026-10-16T09:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "hotel")])
    r = res[t.txn_id]
    assert (r.status, r.reimbursable) == ("FLAG", Decimal("1150.00"))


def test_hotel_over_cap_with_stay_over_10_nights_fails():
    trip = _trip(
        start="2026-10-01T10:00:00+09:00",
        end="2026-10-15T18:00:00+02:00",
        departure_at="2026-10-01T10:00:00+09:00",
        return_arrival_at="2026-10-16T14:30:00+09:00",
        destinations=[{"city": "Paris", "country": "FR",
                       "from": "2026-10-01T00:00:00+02:00", "to": "2026-10-15T23:59:00+02:00"}],
    )
    t = _txn("Hotel Lutetia", "4200", "EUR", "2026-10-14T09:00:00+02:00", 1)
    res, _ = _run(trip, [(t, "hotel")])
    assert res[t.txn_id].status == "FAIL"


def test_meals_same_local_day_aggregate_against_daily_cap(paris_trip):
    a = _txn("Bistro A", "30", "EUR", "2026-10-13T12:00:00+02:00", 1)
    b = _txn("Bistro B", "20", "EUR", "2026-10-13T19:00:00+02:00", 2)
    res, _ = _run(paris_trip, [(a, "meal"), (b, "meal")])
    assert (res[b.txn_id].status, res[b.txn_id].reimbursable) == ("FLAG", Decimal("15.00"))


def test_meal_cap_exhausted_gives_zero_reimbursable(paris_trip):
    a = _txn("Bistro A", "45", "EUR", "2026-10-13T12:00:00+02:00", 1)
    b = _txn("Bistro B", "10", "EUR", "2026-10-13T19:00:00+02:00", 2)
    res, _ = _run(paris_trip, [(a, "meal"), (b, "meal")])
    assert res[b.txn_id].reimbursable == Decimal("0")


def test_kst_timestamp_counts_on_previous_paris_day(paris_trip):
    a = _txn("Bistro A", "30", "EUR", "2026-10-13T12:00:00+02:00", 1)
    b = _txn("Bistro B", "30", "EUR", "2026-10-14T06:30:00+09:00", 2)
    res, _ = _run(paris_trip, [(a, "meal"), (b, "meal")])
    assert res[b.txn_id].reimbursable == Decimal("15.00")


def test_kst_and_paris_timestamps_on_different_local_days_split(paris_trip):
    a = _txn("Bistro A", "40", "EUR", "2026-10-14T06:30:00+09:00", 1)
    b = _txn("Bistro B", "40", "EUR", "2026-10-14T12:00:00+02:00", 2)
    res, _ = _run(paris_trip, [(a, "meal"), (b, "meal")])
    assert [res[a.txn_id].status, res[b.txn_id].status] == ["PASS", "PASS"]


def test_meal_in_usd_in_paris_converted_and_capped(paris_trip):
    fx = StaticFx({("USD", "EUR"): Decimal("0.9")})
    t = _txn("Diner", "60", "USD", "2026-10-13T12:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "meal")], fx)
    assert (res[t.txn_id].status, res[t.txn_id].reimbursable) == ("FLAG", Decimal("50.00"))


def test_meal_in_usd_under_converted_cap_passes(paris_trip):
    fx = StaticFx({("USD", "EUR"): Decimal("0.9")})
    t = _txn("Diner", "40", "USD", "2026-10-13T12:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "meal")], fx)
    assert res[t.txn_id].status == "PASS"


def test_long_term_stay_meal_reimbursable_halved_cap():
    trip = _trip(stay_type="long_term")
    t = _txn("Bistro", "30", "EUR", "2026-10-13T12:00:00+02:00", 1)
    res, _ = _run(trip, [(t, "meal")])
    assert res[t.txn_id].reimbursable == Decimal("22.50")


def test_departure_after_1730_makes_first_day_meal_ineligible():
    trip = _trip(departure_at="2026-10-12T19:00:00+09:00", start="2026-10-12T19:00:00+09:00")
    t = _txn("Bistro", "20", "EUR", "2026-10-12T22:00:00+02:00", 1)
    res, _ = _run(trip, [(t, "meal")])
    r = res[t.txn_id]
    assert r.status == "FLAG" and any("day not eligible" in x for x in r.reasons)


def test_departure_before_1730_first_day_meal_eligible(paris_trip):
    t = _txn("Bistro", "20", "EUR", "2026-10-12T20:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "meal")])
    assert res[t.txn_id].status == "PASS"


def test_arrival_after_1300_last_day_meal_eligible(paris_trip):
    t = _txn("Bistro", "20", "EUR", "2026-10-17T12:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "meal")])
    assert res[t.txn_id].status == "PASS"


def test_arrival_before_1300_last_day_meal_ineligible():
    trip = _trip(return_arrival_at="2026-10-18T11:00:00+09:00")
    t = _txn("Bistro", "20", "EUR", "2026-10-17T12:00:00+02:00", 1)
    res, _ = _run(trip, [(t, "meal")])
    assert any("day not eligible" in x for x in res[t.txn_id].reasons)


def test_insurance_fails_with_zero_reimbursable(paris_trip):
    t = _txn("AXA Assurance", "80", "EUR", "2026-10-13T12:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "insurance")])
    assert (res[t.txn_id].status, res[t.txn_id].reimbursable) == ("FAIL", Decimal("0"))


def test_visa_passes_full_amount(paris_trip):
    t = _txn("VFS Global", "35", "EUR", "2026-10-13T12:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "visa")])
    assert (res[t.txn_id].status, res[t.txn_id].reimbursable) == ("PASS", Decimal("35.00"))


def test_refund_passes_with_negative_reimbursable(paris_trip):
    t = _txn("Bistro", "-50", "EUR", "2026-10-13T12:00:00+02:00", 1)
    res, _ = _run(paris_trip, [(t, "meal")])
    assert (res[t.txn_id].status, res[t.txn_id].reimbursable) == ("PASS", Decimal("-50.00"))


def test_cancelled_transaction_excluded_from_results(paris_trip):
    t = _txn("Bistro", "30", "EUR", "2026-10-13T12:00:00+02:00", 1, status="cancelled")
    res, _ = _run(paris_trip, [(t, "meal")])
    assert t.txn_id not in res


def test_unknown_country_hotel_flags_no_cap_defined():
    trip = _trip(destinations=[{"city": "Sao Paulo", "country": "BR",
                                "from": "2026-10-12T00:00:00-03:00", "to": "2026-10-17T23:59:00-03:00"}],
                 end="2026-10-17T18:00:00-03:00")
    t = _txn("Hotel Unique", "900", "BRL", "2026-10-14T09:00:00-03:00", 1)
    res, _ = _run(trip, [(t, "hotel")])
    r = res[t.txn_id]
    assert r.status == "FLAG" and any("no cap defined" in x for x in r.reasons)


def test_us_car_rental_over_75_per_day_flags_with_capped_reimbursable():
    trip = _trip(
        start="2026-11-02T10:00:00-05:00",
        end="2026-11-06T18:00:00-05:00",
        departure_at="2026-11-02T10:00:00+09:00",
        return_arrival_at="2026-11-07T14:30:00+09:00",
        destinations=[{"city": "Austin", "country": "US",
                       "from": "2026-11-02T00:00:00-05:00", "to": "2026-11-06T23:59:00-05:00"}],
    )
    t = _txn("Hertz", "400", "USD", "2026-11-03T09:00:00-05:00", 1)
    res, _ = _run(trip, [(t, "car_rental")])
    assert (res[t.txn_id].status, res[t.txn_id].reimbursable) == ("FLAG", Decimal("300.00"))
