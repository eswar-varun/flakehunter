from __future__ import annotations

import pytest

from flakehunter.analysis import Status, analyze


def _status(history):
    (verdict,) = analyze(history)
    return verdict


def test_pass_and_fail_on_the_same_commit_is_flaky(ex):
    v = _status([ex("t", "passed", "c1", 1), ex("t", "failed", "c1", 2)])
    assert v.status is Status.FLAKY
    assert (v.flaky_commits, v.commits, v.failures, v.executions) == (1, 1, 1, 2)


def test_a_retry_that_passes_within_one_run_is_flaky(ex):
    v = _status([ex("t", "failed", "c1", 1, attempt=0), ex("t", "passed", "c1", 1, attempt=1)])
    assert v.status is Status.FLAKY


def test_errors_count_as_failures(ex):
    v = _status([ex("t", "passed", "c1", 1), ex("t", "error", "c1", 2)])
    assert v.status is Status.FLAKY


def test_failing_every_time_on_the_latest_commit_is_broken_not_flaky(ex):
    v = _status([ex("t", "passed", "c1", 1), ex("t", "failed", "c2", 2),
                 ex("t", "failed", "c2", 3)])
    assert v.status is Status.BROKEN


def test_a_fixed_regression_is_stable(ex):
    v = _status([ex("t", "failed", "c1", 1), ex("t", "failed", "c1", 2),
                 ex("t", "passed", "c2", 3)])
    assert v.status is Status.STABLE


def test_intermittent_failures_across_commits_are_suspect(ex):
    v = _status([ex("t", "failed", "c1", 1), ex("t", "passed", "c2", 2),
                 ex("t", "failed", "c3", 3), ex("t", "passed", "c4", 4)])
    assert v.status is Status.SUSPECT


def test_an_intermittent_test_failing_on_the_latest_commit_is_treated_as_broken(ex):
    # Conservative on purpose: a real regression must not be waved away as "probably flaky".
    v = _status([ex("t", "failed", "c1", 1), ex("t", "passed", "c2", 2),
                 ex("t", "failed", "c3", 3)])
    assert v.status is Status.BROKEN


def test_skips_are_ignored(ex):
    v = _status([ex("t", "skipped", "c1", 1), ex("t", "passed", "c1", 2)])
    assert (v.status, v.executions) == (Status.STABLE, 1)
    assert _status([ex("t", "skipped", "c1", 1)]).status is Status.SKIPPED


def test_last_failure_is_the_most_recent_message(ex):
    v = _status([ex("t", "failed", "c1", 1, message="old"), ex("t", "passed", "c1", 2),
                 ex("t", "failed", "c1", 3, message="new")])
    assert v.last_failure == "new"


def test_flaky_tests_are_ranked_by_evidence_not_raw_rate(ex):
    # "rare": 1 failure in 2 runs (50%). "frequent": 30 failures in 100 runs (30%).
    rare = [ex("rare", "passed", "c1", 0), ex("rare", "failed", "c1", 1)]
    frequent = [ex("frequent", "failed" if i < 30 else "passed", "c1", i) for i in range(100)]

    verdicts = analyze([*frequent, *rare])

    assert [v.test_id for v in verdicts] == ["frequent", "rare"]
    assert verdicts[0].failure_rate < verdicts[1].failure_rate


def test_report_order_puts_broken_before_flaky_before_suspect_before_stable(ex):
    history = [
        ex("a_stable", "passed", "c1", 1),
        ex("b_suspect", "failed", "c1", 1), ex("b_suspect", "passed", "c2", 2),
        ex("b_suspect", "failed", "c3", 3), ex("b_suspect", "passed", "c4", 4),
        ex("c_flaky", "passed", "c1", 1), ex("c_flaky", "failed", "c1", 2),
        ex("d_broken", "failed", "c1", 1),
    ]
    assert [v.status for v in analyze(history)] == [
        Status.BROKEN, Status.FLAKY, Status.SUSPECT, Status.STABLE]


def test_ungrouped_input_is_rejected(ex):
    history = [ex("a", "passed", "c1", 1), ex("b", "passed", "c1", 1),
               ex("a", "failed", "c1", 2)]
    with pytest.raises(ValueError, match="not grouped"):
        analyze(history)


def test_no_history_means_no_verdicts():
    assert analyze([]) == []
