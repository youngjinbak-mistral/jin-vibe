from __future__ import annotations

import pytest

from conftest import make_txn
from tea.pipeline import select_trip_txns


def test_in_trip_txn_selected(paris_trip):
    t = make_txn("HOTEL PARIS", "200", "EUR", "2026-10-13T12:00:00+02:00")
    assert len(select_trip_txns([t], paris_trip)) == 1


def test_pretrip_foreign_non_travel_category_excluded(paris_trip):
    t = make_txn("MONOPRIX", "40", "EUR", "2026-09-22T12:00:00+02:00", country="FR")
    sel = select_trip_txns([t], paris_trip)
    assert sel == []
