import pytest

from app.money import format_eok, format_krw, parse_krw, parse_manwon


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12억 5,000", 1_250_000_000),
        ("12억5000만", 1_250_000_000),
        ("12억 5,000만원", 1_250_000_000),
        ("8억", 800_000_000),
        ("8.5억", 850_000_000),
        ("5,000", 50_000_000),
        ("5,000만원", 50_000_000),
        ("3천만", 30_000_000),
        ("1억 2천", 120_000_000),
        ("abc", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_krw(text, expected):
    assert parse_krw(text) == expected


def test_parse_manwon():
    assert parse_manwon("250") == 2_500_000
    assert parse_manwon("1,200") == 12_000_000
    assert parse_manwon("2.5") is None


def test_format_krw_roundtrip():
    assert format_krw(1_250_000_000) == "12억 5,000만원"
    assert format_krw(800_000_000) == "8억원"
    assert format_krw(2_500_000) == "250만원"
    assert format_krw(None) == "-"
    assert parse_krw(format_krw(1_234_560_000).replace("원", "")) == 1_234_560_000


def test_format_eok():
    assert format_eok(1_250_000_000) == "12.50억"
