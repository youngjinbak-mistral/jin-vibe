from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..models import Transaction

LLM_MODELS = ("mistral-large-4", "zai-glm-5-3")

CATEGORIES = (
    "hotel", "meal", "flight", "train", "taxi", "public_transport", "car_rental",
    "mileage", "visa", "insurance", "gift", "equipment", "other",
)

PHRASES: list[tuple[str, str]] = [
    ("flight", "air france"),
    ("flight", "korean air"),
    ("flight", "asiana"),
    ("flight", "lufthansa"),
    ("flight", "british airways"),
    ("flight", "united airlines"),
    ("flight", "delta air"),
    ("flight", "emirates"),
    ("flight", "klm"),
    ("flight", "easyjet"),
    ("flight", "ryanair"),
    ("flight", "airlines"),
    ("flight", "항공"),
    ("hotel", "hotel"),
    ("hotel", "hôtel"),
    ("hotel", "novotel"),
    ("hotel", "ibis"),
    ("hotel", "accor"),
    ("hotel", "marriott"),
    ("hotel", "hilton"),
    ("hotel", "hyatt"),
    ("hotel", "airbnb"),
    ("hotel", "booking.com"),
    ("hotel", "expedia"),
    ("hotel", "agoda"),
    ("hotel", "hotels.com"),
    ("hotel", "ihg"),
    ("hotel", "resort"),
    ("hotel", "inn"),
    ("hotel", "호텔"),
    ("meal", "uber eats"),
    ("meal", "deliveroo"),
    ("meal", "restaurant"),
    ("meal", "resto"),
    ("meal", "cafe"),
    ("meal", "café"),
    ("meal", "coffee"),
    ("meal", "bistro"),
    ("meal", "brasserie"),
    ("meal", "boulangerie"),
    ("meal", "bakery"),
    ("meal", "starbucks"),
    ("meal", "pret a manger"),
    ("meal", "mcdonald"),
    ("meal", "burger"),
    ("meal", "pizza"),
    ("meal", "sushi"),
    ("meal", "식당"),
    ("meal", "카페"),
    ("public_transport", "ratp"),
    ("public_transport", "tfl"),
    ("public_transport", "navigo"),
    ("public_transport", "metro"),
    ("public_transport", "subway"),
    ("taxi", "uber"),
    ("taxi", "bolt"),
    ("taxi", "g7"),
    ("taxi", "taxi"),
    ("taxi", "lyft"),
    ("taxi", "grab"),
    ("taxi", "free now"),
    ("taxi", "kakao t"),
    ("taxi", "cab"),
    ("train", "sncf"),
    ("train", "eurostar"),
    ("train", "trainline"),
    ("train", "ouigo"),
    ("train", "db bahn"),
    ("train", "bahn"),
    ("train", "ktx"),
    ("train", "korail"),
    ("train", "amtrak"),
    ("car_rental", "hertz"),
    ("car_rental", "avis"),
    ("car_rental", "sixt"),
    ("car_rental", "europcar"),
    ("car_rental", "enterprise rent"),
    ("car_rental", "rent a car"),
    ("car_rental", "rentacar"),
    ("car_rental", "쏘카"),
    ("visa", "esta"),
    ("visa", "vfs"),
    ("visa", "k-eta"),
    ("visa", "visa fee"),
    ("visa", "etias"),
    ("visa", "eta uk"),
    ("insurance", "insurance"),
    ("insurance", "assurance"),
    ("insurance", "보험"),
    ("gift", "gift"),
    ("gift", "선물"),
    ("mileage", "mileage"),
    ("mileage", "fuel"),
    ("mileage", "gas station"),
    ("mileage", "주유"),
    ("equipment", "equipment"),
]

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (cat, re.compile(r"(?<![A-Za-z0-9])" + re.escape(p) + r"(?![A-Za-z0-9])", re.IGNORECASE))
    for cat, p in PHRASES
]


def classify_heuristic(txn: Transaction) -> str | None:
    m = (txn.merchant or "").lower()
    for cat, pat in _PATTERNS:
        if pat.search(m):
            return cat
    return None


def classify_with_meta(txn: Transaction, llm: Any = None) -> dict:
    h = classify_heuristic(txn)
    if h is not None:
        return {"category": h, "source": "heuristic", "models": {}}
    if llm is None:
        return {"category": "other", "source": "heuristic", "models": {}}
    prompt = (
        f"Classify this card transaction into exactly one category from {list(CATEGORIES)}. "
        f"Merchant: {txn.merchant!r}, amount: {txn.amount} {txn.currency}, country: {txn.country}. "
        'Respond with JSON only: {"category": "..."}'
    )
    def ask(model: str) -> str | None:
        try:
            r = llm.complete_json(model, prompt)
        except Exception:
            return None
        c = str(r.get("category", "")).lower()
        return c if c in CATEGORIES else "other"

    with ThreadPoolExecutor(max_workers=len(LLM_MODELS)) as pool:
        models: dict[str, str | None] = dict(zip(LLM_MODELS, pool.map(ask, LLM_MODELS)))
    c1 = models.get(LLM_MODELS[0])
    c2 = models.get(LLM_MODELS[1])
    if c1 and c2:
        if c1 == c2:
            return {"category": c1, "source": "llm", "models": models}
        return {"category": "other", "source": "llm-disagree", "models": models}
    if c1 or c2:
        return {"category": c1 or c2 or "other", "source": "llm", "models": models}
    return {"category": "other", "source": "llm-disagree", "models": models}


def classify(txn: Transaction, llm: Any = None) -> str:
    return str(classify_with_meta(txn, llm)["category"])
