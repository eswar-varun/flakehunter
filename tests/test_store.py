from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from helpers import T0

from flakehunter.model import CaseResult, Outcome, Run
from flakehunter.store import Store, StoreError

PASS = Outcome.PASSED
FAIL = Outcome.FAILED


def _run(run_id: str, commit: str = "c1", minute: int = 0) -> Run:
    return Run(run_id, commit, T0 + timedelta(minutes=minute))


def test_executions_are_grouped_by_test_and_time_ordered():
    with Store() as store:
        store.add_run(_run("later", minute=5), [CaseResult("t::a", FAIL)])
        store.add_run(_run("earlier", minute=1), [CaseResult("t::a", PASS),
                                                  CaseResult("t::b", PASS)])

        rows = [(e.test_id, e.run_id) for e in store.executions()]

    assert rows == [("t::a", "earlier"), ("t::a", "later"), ("t::b", "earlier")]


def test_uploading_the_same_report_twice_does_not_double_count():
    results = [CaseResult("t::a", PASS), CaseResult("t::b", FAIL)]
    with Store() as store:
        store.add_run(_run("r1"), results)
        store.add_run(_run("r1"), results)

        assert len(list(store.executions())) == 2
        assert store.run_count() == 1


def test_shards_of_one_run_accumulate():
    with Store() as store:
        store.add_run(_run("r1"), [CaseResult("shard1::a", PASS)])
        store.add_run(_run("r1"), [CaseResult("shard2::b", PASS)])

        assert {e.test_id for e in store.executions()} == {"shard1::a", "shard2::b"}


def test_retry_attempts_are_kept_separately():
    with Store() as store:
        store.add_run(_run("r1"), [CaseResult("t::a", FAIL, attempt=0),
                                   CaseResult("t::a", PASS, attempt=1)])

        assert [e.outcome for e in store.executions()] == [FAIL, PASS]


def test_reusing_a_run_id_for_another_commit_is_refused():
    with Store() as store:
        store.add_run(_run("r1", commit="c1"), [CaseResult("t::a", PASS)])
        with pytest.raises(StoreError, match="already recorded for commit c1"):
            store.add_run(_run("r1", commit="c2"), [CaseResult("t::a", FAIL)])

        # The refused write left nothing behind.
        assert [e.outcome for e in store.executions()] == [PASS]


def test_naive_timestamps_are_refused():
    with Store() as store, pytest.raises(StoreError, match="timezone-aware"):
        store.add_run(Run("r1", "c1", datetime(2026, 1, 1)), [])


def test_history_persists_on_disk(tmp_path):
    path = tmp_path / "history.db"
    with Store(path) as store:
        store.add_run(_run("r1"), [CaseResult("t::a", PASS, duration_s=1.5, message=None)])
    with Store(path) as store:
        (row,) = store.executions()
    assert (row.test_id, row.commit, row.duration_s, row.created_at) == ("t::a", "c1", 1.5, T0)
