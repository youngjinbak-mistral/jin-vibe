import pytest

from app.listing_parser import parse_listing


@pytest.mark.parametrize(
    "text,tx,field,value",
    [
        ("전세 8억 84㎡", "JEONSE", "deposit_krw", 800_000_000),
        ("매매 84㎡ 12억", "SALE", "price_krw", 1_200_000_000),
        ("전세 84㎡ 보증금 8억", "JEONSE", "deposit_krw", 800_000_000),
        ("전세 15층 8억", "JEONSE", "deposit_krw", 800_000_000),
        ("매매 12억 5,000", "SALE", "price_krw", 1_250_000_000),
    ],
)
def test_required_regressions(text, tx, field, value):
    p = parse_listing(text, [])
    assert p.tx_type == tx
    assert getattr(p, field) == value
    others = {"price_krw", "deposit_krw", "monthly_rent_krw"} - {field}
    assert all(getattr(p, o) is None for o in others)
    assert not any("금액" in w for w in p.warnings)
