from decimal import Decimal

import pytest

from conftest import make_txn
from tea.policy.classify import classify


def _txn(merchant):
    return make_txn(merchant, Decimal("10.00"), "EUR", "2026-10-13T12:00:00+02:00", country="FR")


class FakeLLM:
    def __init__(self, answers=None, raise_for=()):
        self.answers = answers or {}
        self.raise_for = set(raise_for)
        self.calls = []

    def complete_json(self, model, prompt):
        self.calls.append((model, prompt))
        if model in self.raise_for or "*" in self.raise_for:
            raise RuntimeError("llm down")
        return {"category": self.answers.get(model, "other")}


def test_dinner_club_is_not_hotel_despite_inn_substring():
    assert classify(_txn("DINNER CLUB")) != "hotel"


def test_fairmont_is_not_flight_despite_air_substring():
    assert classify(_txn("FAIRMONT")) in ("hotel", "other")


def test_metal_shop_is_not_visa_despite_eta_substring():
    assert classify(_txn("METAL SHOP")) != "visa"


def test_uber_eats_is_meal():
    assert classify(_txn("UBER EATS PARIS")) == "meal"


def test_plain_uber_is_taxi():
    assert classify(_txn("UBER *TRIP")) == "taxi"


def test_grab_is_taxi():
    assert classify(_txn("GRAB SINGAPORE")) == "taxi"


def test_korean_hotel_compound_is_hotel():
    assert classify(_txn("롯데호텔")) == "hotel"


def test_korean_restaurant_is_meal():
    assert classify(_txn("김밥 식당")) == "meal"


def test_air_france_is_flight():
    assert classify(_txn("AIR FRANCE")) == "flight"


def test_esta_is_visa():
    assert classify(_txn("ESTA APPLICATION")) == "visa"


def test_heuristic_hit_does_not_call_llm():
    llm = FakeLLM({"mistral-large-4": "gift", "zai-glm-5-3": "gift"})
    assert classify(_txn("MARRIOTT OPERA"), llm=llm) == "hotel"
    assert llm.calls == []


def test_llm_agreement_returns_agreed_category():
    llm = FakeLLM({"mistral-large-4": "equipment", "zai-glm-5-3": "equipment"})
    assert classify(_txn("XQZ HOLDINGS 7781"), llm=llm) == "equipment"
    assert any(m == "mistral-large-4" for m, _ in llm.calls)


def test_llm_disagreement_returns_other():
    llm = FakeLLM({"mistral-large-4": "meal", "zai-glm-5-3": "equipment"})
    assert classify(_txn("XQZ HOLDINGS 7781"), llm=llm) == "other"
    models = {m for m, _ in llm.calls}
    assert "mistral-large-4" in models
    assert "zai-glm-5-3" in models


def test_llm_exception_falls_back_without_raising():
    llm = FakeLLM(raise_for=["*"])
    assert classify(_txn("XQZ HOLDINGS 7781"), llm=llm) == "other"


def test_llm_invalid_category_never_leaks_through():
    llm = FakeLLM({"mistral-large-4": "spaceship", "zai-glm-5-3": "spaceship"})
    result = classify(_txn("XQZ HOLDINGS 7781"), llm=llm)
    assert result in (
        "hotel", "meal", "flight", "train", "taxi", "car_rental", "mileage",
        "visa", "insurance", "gift", "equipment", "other", "public_transport",
    )
    assert result != "spaceship"
