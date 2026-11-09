import pytest

from app.listing_parser import mask_non_money, parse_listing
from app.money import format_krw_input, parse_krw_strict, scan_money


def P(text):
    return parse_listing(text, [])


@pytest.mark.parametrize(
    "text,expected",
    [
        ("매매 12억 84㎡ 15층", 1_200_000_000),
        ("매매 84.97㎡ 12억", 1_200_000_000),
        ("매매 84m² 12억", 1_200_000_000),
        ("매매 84m2 12억", 1_200_000_000),
        ("매매 34평 12억", 1_200_000_000),
        ("매매 12억 34평", 1_200_000_000),
        ("매매 112/84㎡ 12억 5,000", 1_250_000_000),
        ("매매 12억 5,000 112.4/84.97㎡", 1_250_000_000),
        ("매매 15/25층 12억", 1_200_000_000),
        ("매매 고/25층 12억", 1_200_000_000),
        ("매매 12억 2025.03.14", 1_200_000_000),
        ("매매 2025.03.14 12억", 1_200_000_000),
        ("매매 25.03.14. 12억", 1_200_000_000),
        ("매매 2025년 3월 14일 12억", 1_200_000_000),
        ("매매 103동 1502호 12억", 1_200_000_000),
        ("매매 2018년 준공 854세대 12억", 1_200_000_000),
        ("매매   12 억   5,000", 1_250_000_000),
        ("매매12억5000", 1_250_000_000),
        ("매매 12억 5,000만원", 1_250_000_000),
        ("매매 12억 5000만", 1_250_000_000),
        ("매매 12억 5천", 1_250_000_000),
        ("매매 12억 5천만원", 1_250_000_000),
        ("매매 12.5억", 1_250_000_000),
        ("매매 1,250,000,000원", 1_250_000_000),
        ("매매가: 12억", 1_200_000_000),
        ("12억 매매", 1_200_000_000),
        ("매매 12억 관리비 25만", 1_200_000_000),
        ("매매 12억 84A타입", 1_200_000_000),
        ("매매 12억\n84㎡\n15층", 1_200_000_000),
        ("매매\n12억 5,000\n84㎡", 1_250_000_000),
    ],
)
def test_sale_numbers_never_leak(text, expected):
    p = P(text)
    assert p.tx_type == "SALE"
    assert p.price_krw == expected


@pytest.mark.parametrize(
    "text,deposit,monthly",
    [
        ("월세 1억/250", 100_000_000, 2_500_000),
        ("월세 1억/250 84㎡", 100_000_000, 2_500_000),
        ("월세 84㎡ 1억/250", 100_000_000, 2_500_000),
        ("월세 1억 / 250", 100_000_000, 2_500_000),
        ("월세 5,000/180", 50_000_000, 1_800_000),
        ("월세 1억 5,000/230 전용 59.96㎡", 150_000_000, 2_300_000),
        ("반전세 3억/100", 300_000_000, 1_000_000),
        ("보증금 1억 월 250", 100_000_000, 2_500_000),
        ("보증금 1억 월 250 59㎡", 100_000_000, 2_500_000),
        ("보증금 1억 월세 250만원 84m²", 100_000_000, 2_500_000),
        ("월세 보증금 5,000 월 180", 50_000_000, 1_800_000),
        ("월세 15층 보증금 1억 월세 250", 100_000_000, 2_500_000),
        ("월세 월 250 보증금 1억", 100_000_000, 2_500_000),
        ("월세 2025.03.14 1억/250", 100_000_000, 2_500_000),
    ],
)
def test_wolse_pairs(text, deposit, monthly):
    p = P(text)
    assert p.tx_type == "WOLSE"
    assert (p.deposit_krw, p.monthly_rent_krw, p.price_krw) == (deposit, monthly, None)


@pytest.mark.parametrize(
    "text",
    [
        "매매 12억 5",
        "매매 12억 84",
        "매매 12억 5,000원",
        "매매 1,250,000,000",
        "매매 12억 13억",
        "전세 8억 9억",
        "매매 84㎡",
        "매매 15층",
        "매매 2025.03.14",
        "매매 2.5",
        "전세 84",
    ],
)
def test_ambiguous_or_missing_flagged_not_guessed(text):
    p = P(text)
    assert p.price_krw is None and p.deposit_krw is None and p.monthly_rent_krw is None
    assert any("금액" in w or "찾지 못했습니다" in w for w in p.warnings)


@pytest.mark.parametrize("text", ["월세 1억", "월세 보증금 1억", "월세 월 250", "월세 1억/250 2억/300"])
def test_wolse_incomplete_or_conflicting_flagged(text):
    p = P(text)
    assert p.deposit_krw is None and p.monthly_rent_krw is None
    assert "월세는 보증금과 월세를 함께 입력해야 합니다" in p.warnings


def test_mask_keeps_money_intact():
    m = mask_non_money("전세 8억 84㎡ 15층 2025.03.14 103동")
    toks = scan_money(m)
    assert [t.value for t in toks] == [800_000_000]


def test_other_amounts_ignored():
    p = P("전세 8억 관리비 25만 융자 2억")
    assert p.deposit_krw == 800_000_000


def test_area_and_floor_still_extracted():
    p = P("매매 84㎡ 12억 15/25층 2025.03.14")
    assert (p.exclusive_m2, p.floor, p.observed_date) == (84.0, "15", "2025-03-14")


def test_amounts_are_exact_ints():
    p = P("매매 12억 3,456")
    assert p.price_krw == 1_234_560_000 and type(p.price_krw) is int


@pytest.mark.parametrize(
    "text,value",
    [
        ("12억 5,000", 1_250_000_000),
        ("12억5000", 1_250_000_000),
        ("12억 5,000만원", 1_250_000_000),
        ("12억 5천", 1_250_000_000),
        ("8억", 800_000_000),
        ("8.5억", 850_000_000),
        ("5,000", 50_000_000),
        ("5,000만원", 50_000_000),
        ("3천만", 30_000_000),
        ("1,250,000,000원", 1_250_000_000),
        ("0", 0),
    ],
)
def test_strict_form_parser_accepts(text, value):
    assert parse_krw_strict(text) == (value, None)


@pytest.mark.parametrize(
    "text",
    ["12억 5", "12억 84㎡", "84㎡", "15층", "12억 13억", "1,250,000,000", "12억 5,000원", "abc", "2.5", "-5억", "1,2345", "12억 15층"],
)
def test_strict_form_parser_rejects(text):
    value, err = parse_krw_strict(text)
    assert value is None and err


@pytest.mark.parametrize("v", [1_250_000_000, 800_000_000, 50_000_000, 1_234_560_000, 2_500_000, 1_000_000_001, 0])
def test_input_format_roundtrip(v):
    assert parse_krw_strict(format_krw_input(v)) == (v, None)
