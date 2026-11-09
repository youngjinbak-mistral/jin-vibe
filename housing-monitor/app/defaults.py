DEFAULT_SETTINGS = {
    "watch_areas": [
        {"gu": "광진구", "dongs": ["광장동", "구의동", "자양동"], "note": "아차산역 일대 포함"},
        {"gu": "성동구", "dongs": ["옥수동", "금호동", "행당동", "응봉동", "성수동"], "note": "서쪽 경계: 옥수동"},
        {"gu": "동대문구", "dongs": [], "note": ""},
        {"gu": "중랑구", "dongs": [], "note": ""},
        {"gu": "송파구", "dongs": [], "note": ""},
        {"gu": "강동구", "dongs": [], "note": ""},
    ],
    "freshness_days": {"ACTUAL": 45, "ASKING": 14},
    "commute_destinations": ["판교", "수원", "공덕"],
    "daycare_anchor": {"name": "파크빌", "enrollment": "2027-03"},
    "auto_sheet_sync": True,
}

SEED_COMPLEXES = [
    {
        "name": "래미안 파크스위트",
        "aliases": "래미안파크스위트, 래미안구의파크스위트",
        "gu": "광진구",
        "dong": "구의동",
        "nearest_station": "아차산역 (5호선)",
        "building_year": 2018,
        "units": 854,
        "molit_lawd_cd": "11215",
        "notes": "기본 예시 단지. 세대수·준공연도는 공개 단지정보 기준이며 직접 확인 후 수정하세요.",
    }
]
