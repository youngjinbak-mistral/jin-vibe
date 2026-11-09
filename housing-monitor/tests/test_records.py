from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import init_db, make_engine
from app.models import Complex, PriceRecord, ReviewItem, UnitType
from app.records import (
    Candidate,
    RecordValidationError,
    ingest,
    resolve_review,
    series_freshness,
    series_points,
)


@pytest.fixture
def db(tmp_path):
    S = init_db(make_engine(f"sqlite:///{tmp_path}/r.db"))
    with S() as s:
        cx = Complex(name="래미안 파크스위트", gu="광진구", dong="구의동")
        cx.unit_types = [UnitType(size_class="59"), UnitType(size_class="84")]
        s.add(cx)
        s.commit()
        yield s


def cand(**kw):
    base = dict(
        complex_id=1, size_class="84", tx_type="SALE", nature="ACTUAL", source_name="국토교통부 실거래가",
        price_krw=2_098_000_000, exclusive_m2=84.98, floor="12", contract_date=date(2026, 9, 3), report_date=date(2026, 10, 14),
    )
    base.update(kw)
    return Candidate(**base)


def test_sale_rejects_deposit(db):
    with pytest.raises(RecordValidationError):
        ingest(db, cand(deposit_krw=900_000_000))


def test_jeonse_rejects_price(db):
    with pytest.raises(RecordValidationError):
        ingest(db, cand(tx_type="JEONSE", price_krw=900_000_000))


def test_wolse_requires_pair(db):
    with pytest.raises(RecordValidationError):
        ingest(db, cand(tx_type="WOLSE", price_krw=None, deposit_krw=100_000_000))
    with pytest.raises(RecordValidationError):
        ingest(db, cand(tx_type="WOLSE", price_krw=None, monthly_rent_krw=2_500_000))
    r = ingest(db, cand(tx_type="WOLSE", price_krw=None, deposit_krw=100_000_000, monthly_rent_krw=2_500_000))
    assert r.outcome == "created"
    assert (r.record.deposit_krw, r.record.monthly_rent_krw, r.record.price_krw) == (100_000_000, 2_500_000, None)


def test_wolse_zero_deposit_allowed(db):
    r = ingest(db, cand(tx_type="WOLSE", price_krw=None, deposit_krw=0, monthly_rent_krw=3_000_000))
    assert r.outcome == "created"


def test_amounts_must_be_int(db):
    with pytest.raises(RecordValidationError):
        ingest(db, cand(price_krw=12.5))
    with pytest.raises(RecordValidationError):
        ingest(db, cand(price_krw=True))


def test_db_constraint_blocks_mixed_series(db):
    rec = ingest(db, cand()).record
    db.commit()
    rec.deposit_krw = 1
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_supply_area_in_exclusive_rejected(db):
    with pytest.raises(RecordValidationError):
        ingest(db, cand(exclusive_m2=112.4))
    with pytest.raises(RecordValidationError):
        ingest(db, cand(size_class="59", exclusive_m2=84.97))
    with pytest.raises(RecordValidationError):
        ingest(db, cand(exclusive_m2=84.97, supply_m2=59.0))


def test_report_before_contract_rejected(db):
    with pytest.raises(RecordValidationError):
        ingest(db, cand(contract_date=date(2026, 9, 3), report_date=date(2026, 9, 1)))


def test_large_amount_kept_exact(db):
    r = ingest(db, cand(price_krw=3_456_789_012)).record
    db.commit()
    db.expire_all()
    assert db.get(PriceRecord, r.id).price_krw == 3_456_789_012


def test_exact_duplicate_not_inserted(db):
    a = ingest(db, cand())
    b = ingest(db, cand())
    assert a.outcome == "created"
    assert b.outcome == "duplicate"
    assert b.record.id == a.record.id
    assert db.scalar(select(PriceRecord.id).where(PriceRecord.id > a.record.id)) is None


def test_same_floor_and_price_different_date_goes_to_review_not_merge(db):
    a = ingest(db, cand())
    b = ingest(db, cand(contract_date=date(2026, 9, 20), report_date=date(2026, 9, 25)))
    assert b.outcome == "ambiguous"
    assert b.review.matched_record_id == a.record.id
    assert db.scalars(select(PriceRecord)).all() == [a.record]


def test_unrelated_record_created(db):
    ingest(db, cand())
    b = ingest(db, cand(price_krw=1_900_000_000, floor="3", contract_date=date(2026, 8, 1), report_date=date(2026, 8, 20)))
    assert b.outcome == "created"


def test_jeonse_does_not_match_sale(db):
    ingest(db, cand())
    j = ingest(db, cand(tx_type="JEONSE", price_krw=None, deposit_krw=2_098_000_000))
    assert j.outcome == "created"


def test_source_id_change_creates_new_version(db):
    a = ingest(db, cand(source_record_id="11215-2026-0001", source_version="1"))
    b = ingest(db, cand(source_record_id="11215-2026-0001", source_version="2", status="CANCELLED"))
    assert b.outcome == "new_version"
    assert b.record.record_uid == a.record.record_uid
    assert b.record.version == 2
    assert b.record.is_current and not a.record.is_current
    assert a.record.status == "ACTIVE"
    assert a.record.price_krw == 2_098_000_000
    assert "status" in b.record.change_reason


def test_source_id_same_data_is_duplicate(db):
    ingest(db, cand(source_record_id="X1", source_version="1"))
    assert ingest(db, cand(source_record_id="X1", source_version="1")).outcome == "duplicate"


def test_source_id_replay_of_old_version_goes_to_review(db):
    ingest(db, cand(source_record_id="X1", source_version="1"))
    ingest(db, cand(source_record_id="X1", source_version="2", price_krw=2_100_000_000))
    r = ingest(db, cand(source_record_id="X1", source_version="1"))
    assert r.outcome == "ambiguous"


def test_source_id_with_different_series_goes_to_review(db):
    ingest(db, cand(source_record_id="X1"))
    r = ingest(db, cand(source_record_id="X1", tx_type="JEONSE", price_krw=None, deposit_krw=900_000_000))
    assert r.outcome == "ambiguous"


def test_resolve_separate(db):
    a = ingest(db, cand())
    b = ingest(db, cand(contract_date=date(2026, 9, 20), report_date=date(2026, 9, 25)))
    rec = resolve_review(db, b.review, "separate")
    assert rec.record_uid != a.record.record_uid
    assert b.review.status == "SEPARATE"
    with pytest.raises(RecordValidationError):
        resolve_review(db, b.review, "discard")


def test_resolve_new_version(db):
    a = ingest(db, cand())
    b = ingest(db, cand(floor="13"))
    rec = resolve_review(db, b.review, "new_version")
    assert rec.record_uid == a.record.record_uid and rec.version == 2
    assert not a.record.is_current


def test_resolve_new_version_rejects_different_source_ids(db):
    ingest(db, cand(source_name="Naver 부동산", nature="ASKING", source_record_id="111", contract_date=None, report_date=date(2026, 9, 1)))
    b = ingest(db, cand(source_name="Naver 부동산", nature="ASKING", source_record_id="222", contract_date=None, report_date=date(2026, 9, 1), floor="12"))
    assert b.outcome == "created"
    c = ingest(db, cand(source_name="Naver 부동산", nature="ASKING", source_record_id=None, contract_date=None, report_date=date(2026, 9, 2)))
    assert c.outcome == "ambiguous"


def test_series_points_never_mix_types(db):
    ingest(db, cand())
    ingest(db, cand(tx_type="JEONSE", price_krw=None, deposit_krw=950_000_000, floor="5"))
    ingest(db, cand(tx_type="WOLSE", price_krw=None, deposit_krw=100_000_000, monthly_rent_krw=2_500_000, floor="7"))
    for tx in ("SALE", "JEONSE", "WOLSE"):
        pts = series_points(db, 1, tx, ["59", "84"], ["ACTUAL", "ASKING"])
        assert {p.tx_type for p in pts} == {tx}
    with pytest.raises(RecordValidationError):
        series_points(db, 1, "BOGUS", ["84"], ["ACTUAL"])


def test_series_points_only_current_versions(db):
    ingest(db, cand(source_record_id="X1"))
    ingest(db, cand(source_record_id="X1", price_krw=2_000_000_000))
    pts = series_points(db, 1, "SALE", ["84"], ["ACTUAL"])
    assert [p.price_krw for p in pts] == [2_000_000_000]


def test_freshness(db):
    r = ingest(db, cand()).record
    db.commit()
    f = series_freshness(db, 1, "SALE", "84", "ACTUAL", {"ACTUAL": 45}, now=r.captured_at + timedelta(days=10))
    assert not f.stale and f.count == 1
    f = series_freshness(db, 1, "SALE", "84", "ACTUAL", {"ACTUAL": 45}, now=r.captured_at + timedelta(days=46))
    assert f.stale
    f = series_freshness(db, 1, "JEONSE", "84", "ACTUAL", {"ACTUAL": 45}, now=datetime(2030, 1, 1))
    assert not f.stale and f.count == 0


def test_estimate_flag_persisted(db):
    r = ingest(db, cand(is_estimate=True, estimate_note="주차 데이터 없음")).record
    assert r.is_estimate
    plain = ingest(db, cand())
    assert plain.outcome in ("created", "ambiguous")
