import pytest

from app.listing_parser import ComplexRef, ParsedListing, parse_listing

COMPLEXES = [
    ComplexRef(id=1, name="래미안 강나루", aliases=["래미안강나루"]),
    ComplexRef(id=2, name="래미안 강북", aliases=["강북 래미안"]),
    ComplexRef(id=3, name="힐스테이트", aliases=["힐스테이트 서울"]),
]


def test_sale_price():
    p = parse_listing("래미안 강나루 매매 12억 5,000", COMPLEXES)
    assert p.tx_type == "SALE"
    assert p.price_krw == 1_250_000_000
    assert p.deposit_krw is None
    assert p.complex_id == 1


def test_sale_price_no_space():
    p = parse_listing("매매12억5000", COMPLEXES)
    assert p.price_krw == 1_250_000_000


def test_jeonse_never_price():
    p = parse_listing("래미안 강나루 전세 7억", COMPLEXES)
    assert p.tx_type == "JEONSE"
    assert p.deposit_krw == 700_000_000
    assert p.price_krw is None


def test_wolse_slash_pair():
    p = parse_listing("월세 1억/250", COMPLEXES)
    assert p.tx_type == "WOLSE"
    assert p.deposit_krw == 100_000_000
    assert p.monthly_rent_krw == 2_500_000


def test_wolse_manwon_deposit():
    p = parse_listing("월세 5,000/180", COMPLEXES)
    assert p.deposit_krw == 50_000_000
    assert p.monthly_rent_krw == 1_800_000


def test_wolse_deposit_only_warns():
    p = parse_listing("월세 보증금 1억", COMPLEXES)
    assert p.deposit_krw is None
    assert p.monthly_rent_krw is None
    assert "월세는 보증금과 월세를 함께 입력해야 합니다" in p.warnings


def test_wolse_bogeum_month():
    p = parse_listing("보증금 1억 월 250", COMPLEXES)
    assert p.deposit_krw == 100_000_000
    assert p.monthly_rent_krw == 2_500_000


def test_banjeonse():
    p = parse_listing("반전세 3억/100", COMPLEXES)
    assert p.tx_type == "WOLSE"
    assert p.deposit_krw == 300_000_000
    assert p.monthly_rent_krw == 1_000_000


def test_multiple_types():
    p = parse_listing("매매 12억 전세 7억", COMPLEXES)
    assert p.tx_type is None
    assert "거래유형이 여러 개 감지됨" in p.warnings


def test_nature_actual():
    p = parse_listing("실거래가 매매 12억 5,000", COMPLEXES)
    assert p.nature == "ACTUAL"
    assert p.tx_type == "SALE"


def test_price_without_type_keyword_is_not_guessed():
    p = parse_listing("실거래가 12억 5,000", COMPLEXES)
    assert p.tx_type is None
    assert p.price_krw is None
    assert p.deposit_krw is None


def test_nature_asking_default():
    p = parse_listing("매매 7억", COMPLEXES)
    assert p.nature == "ASKING"


def test_exclusive_sqm():
    p = parse_listing("전용 84.97㎡ 전세 7억", COMPLEXES)
    assert p.exclusive_m2 == 84.97
    assert p.size_class == "84"


def test_supply_label():
    p = parse_listing("공급 112.4㎡ 매매 12억", COMPLEXES)
    assert p.supply_m2 == 112.4
    assert p.exclusive_m2 is None
    assert p.size_class is None


def test_slash_pair_areas():
    p = parse_listing("112.4/84.97㎡ 매매 12억", COMPLEXES)
    assert p.supply_m2 == 112.4
    assert p.exclusive_m2 == 84.97


def test_pyeong_only_supply():
    p = parse_listing("34평 매매 12억", COMPLEXES)
    assert p.supply_m2 == pytest.approx(112.4, abs=0.01)
    assert p.exclusive_m2 is None


def test_lone_sqm_assumed_exclusive():
    p = parse_listing("매매 12억 84㎡", COMPLEXES)
    assert p.exclusive_m2 == 84.0
    assert any("전용으로 가정" in w for w in p.warnings)


def test_size_59():
    p = parse_listing("전용 59.94㎡ 전세 7억", COMPLEXES)
    assert p.size_class == "59"


def test_type_label_84A():
    p = parse_listing("84A타입 매매 12억", COMPLEXES)
    assert p.size_class == "84"
    assert p.exclusive_m2 is None


def test_floor_numeric():
    p = parse_listing("매매 12억 12/25층", COMPLEXES)
    assert p.floor == "12"


def test_floor_gao():
    p = parse_listing("매매 12억 고/25층", COMPLEXES)
    assert p.floor == "고"


def test_floor_jeo():
    p = parse_listing("매매 12억 저층", COMPLEXES)
    assert p.floor == "저"


def test_date_dot():
    p = parse_listing("매매 12억 확인 2025.03.14", COMPLEXES)
    assert p.observed_date == "2025-03-14"


def test_date_two_digit_year():
    p = parse_listing("매매 12억 25.03.14.", COMPLEXES)
    assert p.observed_date == "2025-03-14"


def test_date_korean():
    p = parse_listing("매매 12억 2025년 3월 14일", COMPLEXES)
    assert p.observed_date == "2025-03-14"


def test_no_date():
    p = parse_listing("매매 12억", COMPLEXES, today=__import__("datetime").date(2025, 1, 1))
    assert p.observed_date is None


def test_naver_url():
    text = "https://new.land.naver.com/articles/12345678 매매 12억"
    p = parse_listing(text, COMPLEXES)
    assert p.source_name == "Naver 부동산"
    assert p.source_listing_id == "12345678"
    assert p.source_url.startswith("https://new.land.naver.com")


def test_naver_url_article_no_param():
    p = parse_listing("https://m.land.naver.com/complex?articleNo=998877 매매 12억", COMPLEXES)
    assert p.source_listing_id == "998877"


def test_hogangnono_url():
    p = parse_listing("https://hogangnono.com/someone 매매 12억", COMPLEXES)
    assert p.source_name == "호갱노노"
    assert p.source_listing_id is None


def test_no_source():
    p = parse_listing("매매 12억", COMPLEXES)
    assert p.source_name is None
    assert p.source_url is None


def test_complex_alias_match():
    p = parse_listing("강북 래미안 매매 12억", COMPLEXES)
    assert p.complex_id == 2


def test_complex_tie_warning():
    cs = [
        ComplexRef(id=1, name="래미안", aliases=[]),
        ComplexRef(id=2, name="래미안 팰", aliases=["래미안"]),
    ]
    p = parse_listing("래미안 매매 12억", cs)
    assert p.complex_id is None
    assert any("동일하게 매칭" in w for w in p.warnings)


def test_complex_guess_first_line():
    p = parse_listing("헬리오시티\n매매 12억", COMPLEXES)
    assert p.complex_id is None
    assert p.complex_name_guess == "헬리오시티"


def test_longest_match_wins():
    cs = [
        ComplexRef(id=1, name="힐스테이트", aliases=[]),
        ComplexRef(id=3, name="힐스테이트", aliases=["힐스테이트 서울"]),
    ]
    p = parse_listing("힐스테이트 서울 매매 12억", cs)
    assert p.complex_id == 3


def test_empty_text_no_crash():
    p = parse_listing("", COMPLEXES)
    assert p.tx_type is None
    assert p.complex_id is None


def test_emoji_no_crash():
    p = parse_listing("🏠✨ 매매 12억 🎉", COMPLEXES)
    assert p.price_krw == 1_200_000_000


def test_only_url_no_crash():
    p = parse_listing("https://example.com", COMPLEXES)
    assert p.source_url == "https://example.com"
    assert p.source_name is None


def test_result_is_parsed_listing():
    p = parse_listing("매매 12억", COMPLEXES)
    assert isinstance(p, ParsedListing)


def test_naver_style_jeonse_block():
    text = """래미안 강나루 101동
전세 7억 5,000
112.4/84.97㎡, 12/25층, 남향
확인 25.03.14.
https://new.land.naver.com/complexes/1?articleNo=2512345678"""
    p = parse_listing(text, COMPLEXES)
    assert p.tx_type == "JEONSE"
    assert p.deposit_krw == 750_000_000
    assert p.price_krw is None
    assert p.monthly_rent_krw is None
    assert p.exclusive_m2 == 84.97
    assert p.supply_m2 == 112.4
    assert p.size_class == "84"
    assert p.floor == "12"
    assert p.observed_date == "2025-03-14"
    assert p.source_listing_id == "2512345678"
    assert p.complex_id == 1


def test_wolse_deposit_eok_and_man():
    p = parse_listing("월세 1억 5,000/230 전용 59.96㎡", COMPLEXES)
    assert p.tx_type == "WOLSE"
    assert p.deposit_krw == 150_000_000
    assert p.monthly_rent_krw == 2_300_000
    assert p.size_class == "59"


def test_url_digits_do_not_leak_into_fields():
    p = parse_listing("https://new.land.naver.com/articles/2025031412", COMPLEXES)
    assert p.observed_date is None
    assert p.floor is None
    assert p.exclusive_m2 is None
    assert p.source_listing_id == "2025031412"


def test_invalid_date_ignored():
    p = parse_listing("매매 10억 2025.13.45", COMPLEXES)
    assert p.observed_date is None
