from pathlib import Path

import pytest

from tea.ledger import Ledger


@pytest.fixture
def ledger(tmp_path: Path):
    lg = Ledger(tmp_path / "sub" / "ledger.db")
    yield lg
    lg.close()


def test_unknown_txn_has_no_status(ledger):
    assert ledger.get("nope") is None


def test_new_to_drafted_to_submitted(ledger):
    ledger.set("t1", "drafted")
    assert ledger.get("t1") == "drafted"
    ledger.set("t1", "submitted", ref="DEEL-1")
    assert ledger.get("t1") == "submitted"


def test_new_to_skipped(ledger):
    ledger.set("t1", "skipped")
    assert ledger.get("t1") == "skipped"


def test_drafted_to_skipped(ledger):
    ledger.set("t1", "drafted")
    ledger.set("t1", "skipped")
    assert ledger.get("t1") == "skipped"


def test_redraft_is_allowed(ledger):
    ledger.set("t1", "drafted")
    ledger.set("t1", "drafted")
    assert ledger.get("t1") == "drafted"


def test_submitted_cannot_be_submitted_again(ledger):
    ledger.set("t1", "drafted")
    ledger.set("t1", "submitted", ref="R1")
    with pytest.raises(ValueError):
        ledger.set("t1", "submitted", ref="R2")
    assert ledger.get("t1") == "submitted"


@pytest.mark.parametrize("target", ["drafted", "skipped"])
def test_submitted_is_terminal(ledger, target):
    ledger.set("t1", "drafted")
    ledger.set("t1", "submitted", ref="R1")
    with pytest.raises(ValueError):
        ledger.set("t1", target)
    assert ledger.get("t1") == "submitted"


def test_skipped_to_drafted_via_set_raises(ledger):
    ledger.set("t1", "skipped")
    with pytest.raises(ValueError):
        ledger.set("t1", "drafted")
    assert ledger.get("t1") == "skipped"


def test_skipped_to_submitted_raises(ledger):
    ledger.set("t1", "skipped")
    with pytest.raises(ValueError):
        ledger.set("t1", "submitted")
    assert ledger.get("t1") == "skipped"


def test_reopen_moves_skipped_to_drafted(ledger):
    ledger.set("t1", "skipped")
    ledger.reopen("t1")
    assert ledger.get("t1") == "drafted"
    ledger.set("t1", "submitted", ref="R")
    assert ledger.get("t1") == "submitted"


def test_reopen_rejects_non_skipped(ledger):
    ledger.set("t1", "drafted")
    with pytest.raises(ValueError):
        ledger.reopen("t1")
    ledger.set("t1", "submitted")
    with pytest.raises(ValueError):
        ledger.reopen("t1")
    assert ledger.get("t1") == "submitted"


def test_reopen_unknown_txn_raises(ledger):
    with pytest.raises(ValueError):
        ledger.reopen("ghost")


@pytest.mark.parametrize("bad", ["new", "approved", "SUBMITTED", ""])
def test_unknown_status_rejected(ledger, bad):
    with pytest.raises(ValueError):
        ledger.set("t1", bad)
    assert ledger.get("t1") is None


def test_ref_is_kept_and_listed(ledger):
    ledger.set("t1", "drafted")
    ledger.set("t1", "submitted", ref="DEEL-42")
    rows = {r["txn_id"]: r for r in ledger.all()}
    assert rows["t1"]["ref"] == "DEEL-42"
    assert rows["t1"]["status"] == "submitted"


def test_transactions_are_independent(ledger):
    ledger.set("a", "drafted")
    ledger.set("a", "submitted")
    ledger.set("b", "drafted")
    assert ledger.get("a") == "submitted"
    assert ledger.get("b") == "drafted"


def test_state_persists_across_instances(tmp_path: Path):
    path = tmp_path / "ledger.db"
    first = Ledger(path)
    first.set("t1", "drafted")
    first.set("t1", "submitted", ref="R1")
    first.set("t2", "skipped")
    first.close()
    with Ledger(path) as second:
        assert second.get("t1") == "submitted"
        assert second.get("t2") == "skipped"
        with pytest.raises(ValueError):
            second.set("t1", "submitted")
