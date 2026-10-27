from __future__ import annotations

import random
from datetime import timedelta

import pytest
from helpers import T0

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from flakehunter.analysis import analyze  # noqa: E402
from flakehunter.dynamo import MAX_TRANSACTION_ITEMS, DynamoStore, create_table  # noqa: E402
from flakehunter.model import CaseResult, Outcome, Run  # noqa: E402
from flakehunter.store import Store, StoreError  # noqa: E402

PASS = Outcome.PASSED
FAIL = Outcome.FAILED


@pytest.fixture
def store():
    with moto.mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_table(client, "flakehunter-test")
        yield DynamoStore("flakehunter-test", client=client)


def _run(run_id: str, commit: str = "c1", minute: int = 0) -> Run:
    return Run(run_id, commit, T0 + timedelta(minutes=minute))


def test_executions_are_grouped_by_test_and_time_ordered(store):
    store.add_run("p", _run("later", minute=5), [CaseResult("t::a", FAIL)])
    store.add_run("p", _run("earlier", minute=1), [CaseResult("t::a", PASS),
                                                   CaseResult("t::b", PASS)])

    rows = [(e.test_id, e.run_id) for e in store.executions("p")]

    assert rows == [("t::a", "earlier"), ("t::a", "later"), ("t::b", "earlier")]


def test_uploading_the_same_report_twice_does_not_double_count(store):
    results = [CaseResult("t::a", PASS), CaseResult("t::b", FAIL)]
    store.add_run("p", _run("r1"), results)
    store.add_run("p", _run("r1"), results)

    assert len(list(store.executions("p"))) == 2
    assert store.run_count("p") == 1


def test_a_retried_upload_with_a_later_timestamp_still_overwrites(store):
    # The sort key contains the run's time, so a retry stamped "now" must reuse the time
    # recorded by the first upload or it would land on new keys and double-count.
    store.add_run("p", _run("r1", minute=0), [CaseResult("t::a", FAIL)])
    store.add_run("p", _run("r1", minute=9), [CaseResult("t::a", FAIL)])

    [only] = store.executions("p")
    assert only.created_at == T0


def test_shards_of_one_run_accumulate(store):
    store.add_run("p", _run("r1"), [CaseResult("shard1::a", PASS)])
    store.add_run("p", _run("r1", minute=2), [CaseResult("shard2::b", PASS)])

    assert {e.test_id for e in store.executions("p")} == {"shard1::a", "shard2::b"}
    assert {e.created_at for e in store.executions("p")} == {T0}


def test_retry_attempts_are_kept_separately(store):
    store.add_run("p", _run("r1"), [CaseResult("t::a", FAIL, attempt=0),
                                    CaseResult("t::a", PASS, attempt=1)])

    assert [e.outcome for e in store.executions("p")] == [FAIL, PASS]


def test_reusing_a_run_id_for_another_commit_is_refused(store):
    store.add_run("p", _run("r1", commit="c1"), [CaseResult("t::a", PASS)])
    with pytest.raises(StoreError, match="already recorded for commit c1"):
        store.add_run("p", _run("r1", commit="c2"), [CaseResult("t::a", FAIL)])

    assert [e.commit for e in store.executions("p")] == ["c1"]


def test_projects_are_isolated(store):
    store.add_run("alpha", _run("r1"), [CaseResult("t::a", PASS)])
    store.add_run("beta", _run("r1", commit="other"), [CaseResult("t::a", FAIL)])

    assert [e.outcome for e in store.executions("alpha")] == [PASS]
    assert [e.outcome for e in store.executions("beta")] == [FAIL]


def test_one_tests_history_excludes_tests_whose_id_extends_it(store):
    # "t::a#2" is why the separator isn't "#": the prefix "t::a#" would match it.
    store.add_run("p", _run("r1"), [CaseResult("t::a", PASS), CaseResult("t::ab", FAIL),
                                    CaseResult("t::a[1]", FAIL), CaseResult("t::a#2", FAIL)])

    assert [e.test_id for e in store.executions("p", test_id="t::a")] == ["t::a"]


def test_large_reports_are_split_into_transactions_without_splitting_a_test(store):
    results = [CaseResult(f"t::test_{i:03d}", outcome, attempt=attempt)
               for i in range(150)
               for attempt, outcome in enumerate((FAIL, PASS) if i % 3 == 0 else (PASS,))]
    calls = []
    real = store._client.transact_write_items

    def spy(**kwargs):
        calls.append([item["Put"]["Item"]["test_id"]["S"] for item in kwargs["TransactItems"]])
        return real(**kwargs)

    store._client.transact_write_items = spy

    assert store.add_run("p", _run("r1"), results) == len(results)

    assert len(calls) > 1
    assert all(len(call) <= MAX_TRANSACTION_ITEMS for call in calls)
    # Every attempt of a test lands in the same transaction, so a failed first attempt is
    # never visible without the retry that passed.
    owner = {}
    for index, call in enumerate(calls):
        for test_id in call:
            assert owner.setdefault(test_id, index) == index
    assert len(list(store.executions("p"))) == len(results)


def test_test_ids_with_awkward_characters_round_trip(store):
    ids = ["t::test_x[a|b]", "t::test_y[#1]", "suite with spaces::name", "t::ünïcode"]
    store.add_run("p", _run("r1"), [CaseResult(i, PASS) for i in ids])

    assert sorted(e.test_id for e in store.executions("p")) == sorted(ids)


@pytest.mark.parametrize("project", ["", "has space", "a/b", "x" * 101])
def test_invalid_project_names_are_refused(store, project):
    with pytest.raises(StoreError, match="project"):
        store.add_run(project, _run("r1"), [CaseResult("t::a", PASS)])


def test_analysis_matches_the_sqlite_store_on_the_same_history(store):
    rng = random.Random(7)
    with Store() as sqlite:
        for n in range(12):
            run = _run(f"run-{n}", commit=f"c{n // 3}", minute=n)
            results = [CaseResult(f"t::test_{i}", FAIL if rng.random() < 0.2 * (i % 3) else PASS)
                       for i in range(8)]
            sqlite.add_run(run, results)
            store.add_run("p", run, results)

        assert analyze(store.executions("p")) == analyze(sqlite.executions())
