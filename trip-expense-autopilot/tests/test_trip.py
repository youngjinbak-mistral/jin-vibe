import dataclasses
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from conftest import make_txn

from tea.fx import StaticFx
from tea.policy.rules import evaluate, hotel_cap, meal_cap
from tea.trip import Trip, normalize_city

KST = ZoneInfo("Asia/Seoul")
PARIS = ZoneInfo("Europe/Paris")


def cats(*txns_cats):
    return {t.txn_id: c for t, c in txns_cats}


def run(txns, trip, cats_map, fx=None):
    return evaluate(txns, trip, fx or StaticFx({}), cats_map)


def test_local_dt_converts_kst_to_paris(paris_trip):
    dt = paris_trip.local_dt(datetime(2026, 10, 14, 6, 30, tzinfo=KST))
    assert dt.date() == date(2026, 10, 13)
    assert (dt.hour, dt.minute) == (23, 30)
    assert dt.utcoffset().total_seconds() == 2 * 3600


def test_location_for_inside_and_outside(paris_trip):
    city, country = paris_trip.location_for(datetime(2026, 10, 15, 12, 0, tzinfo=PARIS))
    assert (city, country) == ("Paris", "FR")
    assert paris_trip.location_for(datetime(2026, 10, 20, 12, 0, tzinfo=PARIS)) == (None, None)


def test_nights(paris_trip):
    assert paris_trip.nights() == 5


def test_eligible_meal_day_first_day_before_1730(paris_trip):
    assert paris_trip.eligible_meal_day(date(2026, 10, 12)) is True
    late = dataclasses.replace(
        paris_trip, departure_at=datetime(2026, 10, 12, 18, 0, tzinfo=KST)
    )
    assert late.eligible_meal_day(date(2026, 10, 12)) is False


def test_eligible_meal_day_last_day_after_1300(paris_trip):
    assert paris_trip.eligible_meal_day(date(2026, 10, 17)) is True
    early = dataclasses.replace(
        paris_trip, return_arrival_at=datetime(2026, 10, 18, 12, 0, tzinfo=KST)
    )
    assert early.eligible_meal_day(date(2026, 10, 17)) is False


def test_eligible_meal_day_middle_day(paris_trip):
    assert paris_trip.eligible_meal_day(date(2026, 10, 14)) is True


def test_normalize_city_aliases():
    assert normalize_city("Brussels") == "bruxelles"
    assert normalize_city("NYC") == "new york"
    assert normalize_city("New York City") == "new york"
    assert normalize_city("SF") == "san francisco"


def test_hotel_cap_city_vs_country():
    assert hotel_cap("London", "GB") == (Decimal("260"), "GBP")
    assert hotel_cap("Manchester", "GB") == (Decimal("150"), "GBP")
    assert hotel_cap("Paris", "FR") == (Decimal("230"), "EUR")
    assert hotel_cap("Lyon", "FR") == (Decimal("180"), "EUR")


def test_hotel_cap_aliases_and_cities():
    assert hotel_cap("Brussels", "BE") == (Decimal("250"), "EUR")
    assert hotel_cap("Montréal", "CA") == (Decimal("350"), "CAD")
    assert hotel_cap("NYC", "US") == (Decimal("350"), "USD")
    assert hotel_cap("San Francisco", "US") == (Decimal("475"), "USD")
    assert hotel_cap("Palo Alto", "US") == (Decimal("475"), "USD")


def test_hotel_cap_country_levels():
    assert hotel_cap("Singapore", "SG") == (Decimal("400"), "SGD")
    assert hotel_cap("Dubai", "AE") == (Decimal("1000"), "AED")
    assert hotel_cap("Casablanca", "MA") == (Decimal("1500"), "MAD")


def test_hotel_multinight_under_cap_pass(paris_trip):
    t = make_txn("Hotel Paris", Decimal("1050"), "EUR", "2026-10-14T15:00+02:00")
    res = run([t], paris_trip, cats((t, "hotel")))[t.txn_id]
    assert res.status == "PASS"
    assert res.reimbursable == Decimal("1050.00")


def test_hotel_multinight_over_cap_flag_reimbursable(paris_trip):
    t = make_txn("Hotel Paris", Decimal("1300"), "EUR", "2026-10-14T15:00+02:00")
    res = run([t], paris_trip, cats((t, "hotel")))[t.txn_id]
    assert res.status == "FLAG"
    assert res.reimbursable == Decimal("1150.00")
    assert res.cap == Decimal("230")
    assert res.cap_currency == "EUR"


def test_hotel_over_cap_long_stay_fails():
    trip = Trip.from_dict({
        "id": "LONG",
        "start": "2026-10-01T10:00+09:00",
        "end": "2026-10-13T18:00+02:00",
        "destinations": [{"city": "Paris", "country": "FR",
                          "from": "2026-10-01T00:00+02:00", "to": "2026-10-13T23:59+02:00"}],
    })
    t = make_txn("Hotel Paris", Decimal("3000"), "EUR", "2026-10-05T15:00+02:00")
    res = run([t], trip, cats((t, "hotel")))[t.txn_id]
    assert res.status == "FAIL"
    assert res.reimbursable == Decimal("0.00")


def test_meal_daily_cap_aggregates_same_local_day(paris_trip):
    t1 = make_txn("Cafe A", Decimal("30"), "EUR", "2026-10-14T12:00+02:00")
    t2 = make_txn("Cafe B", Decimal("30"), "EUR", "2026-10-14T20:00+02:00")
    res = run([t1, t2], paris_trip, cats((t1, "meal"), (t2, "meal")))
    assert res[t1.txn_id].status == "PASS"
    assert res[t1.txn_id].reimbursable == Decimal("30.00")
    assert res[t2.txn_id].status == "FLAG"
    assert res[t2.txn_id].reimbursable == Decimal("15.00")


def test_meal_kst_timestamps_split_paris_days(paris_trip):
    t1 = make_txn("Cafe A", Decimal("40"), "EUR", "2026-10-14T06:30+09:00")
    t2 = make_txn("Cafe B", Decimal("40"), "EUR", "2026-10-14T07:30+09:00")
    assert paris_trip.local_dt(t1.approved_at).date() == date(2026, 10, 13)
    assert paris_trip.local_dt(t2.approved_at).date() == date(2026, 10, 14)
    res = run([t1, t2], paris_trip, cats((t1, "meal"), (t2, "meal")))
    assert res[t1.txn_id].status == "PASS"
    assert res[t2.txn_id].status == "PASS"
    assert res[t2.txn_id].reimbursable == Decimal("40.00")


def test_meal_usd_in_paris_converted_via_fx(paris_trip):
    fx = StaticFx({("USD", "EUR"): Decimal("0.9")})
    t = make_txn("Diner", Decimal("60"), "USD", "2026-10-14T12:00+02:00")
    res = run([t], paris_trip, cats((t, "meal")), fx=fx)[t.txn_id]
    assert res.status == "FLAG"
    assert res.reimbursable == Decimal("50.00")


def test_long_term_halves_meal_cap(paris_trip):
    trip = dataclasses.replace(paris_trip, stay_type="long_term")
    assert meal_cap("Paris", "FR", long_term=True) == (Decimal("22.50"), "EUR")
    t = make_txn("Cafe", Decimal("30"), "EUR", "2026-10-14T12:00+02:00")
    res = run([t], trip, cats((t, "meal")))[t.txn_id]
    assert res.status == "FLAG"
    assert res.reimbursable == Decimal("22.50")


def test_meal_first_day_departure_after_1730_not_eligible(paris_trip):
    trip = dataclasses.replace(
        paris_trip, departure_at=datetime(2026, 10, 12, 18, 0, tzinfo=KST)
    )
    t = make_txn("Cafe", Decimal("20"), "EUR", "2026-10-12T20:00+02:00")
    res = run([t], trip, cats((t, "meal")))[t.txn_id]
    assert res.status == "FLAG"
    assert "day not eligible" in res.reasons
    assert res.reimbursable == Decimal("0.00")


def test_insurance_fails(paris_trip):
    t = make_txn("InsureCo", Decimal("100"), "EUR", "2026-10-14T12:00+02:00")
    res = run([t], paris_trip, cats((t, "insurance")))[t.txn_id]
    assert res.status == "FAIL"
    assert res.reimbursable == Decimal("0.00")


def test_visa_passes(paris_trip):
    t = make_txn("VFS", Decimal("80"), "EUR", "2026-10-14T12:00+02:00")
    res = run([t], paris_trip, cats((t, "visa")))[t.txn_id]
    assert res.status == "PASS"
    assert res.reimbursable == Decimal("80.00")


def test_refund_negative_passes(paris_trip):
    t = make_txn("Cafe", Decimal("-50"), "EUR", "2026-10-14T12:00+02:00")
    res = run([t], paris_trip, cats((t, "meal")))[t.txn_id]
    assert res.status == "PASS"
    assert res.reimbursable == Decimal("-50.00")


def test_cancelled_excluded(paris_trip):
    t = make_txn("Cafe", Decimal("20"), "EUR", "2026-10-14T12:00+02:00", status="cancelled")
    res = run([t], paris_trip, cats((t, "meal")))
    assert t.txn_id not in res


def test_unknown_country_flag(paris_trip):
    trip = Trip.from_dict({
        "id": "BR",
        "start": "2026-06-01T10:00+09:00",
        "end": "2026-06-05T18:00-03:00",
        "destinations": [{"city": "Rio", "country": "BR",
                          "from": "2026-06-01T00:00-03:00", "to": "2026-06-05T23:59-03:00"}],
    })
    t = make_txn("Cafe", Decimal("20"), "BRL", "2026-06-03T12:00-03:00")
    res = run([t], trip, cats((t, "meal")))[t.txn_id]
    assert res.status == "FLAG"
    assert "no cap defined" in res.reasons


def test_meal_caps_country_levels():
    assert meal_cap("Zurich", "CH") == (Decimal("50"), "CHF")
    assert meal_cap("Warsaw", "PL") == (Decimal("150"), "PLN")
    assert meal_cap("Singapore", "SG") == (Decimal("55"), "SGD")
    assert meal_cap("London", "GB") == (Decimal("50"), "GBP")


def test_us_car_rental_daily_cap():
    trip = Trip.from_dict({
        "id": "US",
        "start": "2026-07-01T10:00+09:00",
        "end": "2026-07-04T18:00-04:00",
        "destinations": [{"city": "New York", "country": "US",
                          "from": "2026-07-01T00:00-04:00", "to": "2026-07-04T23:59-04:00"}],
    })
    over = make_txn("Hertz", Decimal("300"), "USD", "2026-07-02T12:00-04:00")
    res = run([over], trip, cats((over, "car_rental")))[over.txn_id]
    assert res.status == "FLAG"
    assert res.reimbursable == Decimal("225.00")
    ok = make_txn("Hertz", Decimal("150"), "USD", "2026-07-02T12:00-04:00")
    res = run([ok], trip, cats((ok, "car_rental")))[ok.txn_id]
    assert res.status == "PASS"
    assert res.reimbursable == Decimal("150.00")
