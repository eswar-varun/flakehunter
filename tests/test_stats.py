from __future__ import annotations

import pytest

from flakehunter.stats import wilson_lower_bound


def test_more_evidence_beats_a_higher_raw_rate():
    # The motivating case: 1/1 (100%) must not outrank 30/100 (30%).
    assert wilson_lower_bound(30, 100) > wilson_lower_bound(1, 1)


@pytest.mark.parametrize(("failures", "trials", "expected"), [
    (1, 1, 0.2065),
    (30, 100, 0.2189),
    (5, 10, 0.2366),
    (10, 10, 0.7225),
])
def test_known_values(failures, trials, expected):
    assert wilson_lower_bound(failures, trials) == pytest.approx(expected, abs=1e-4)


def test_no_failures_or_no_trials_is_zero():
    assert wilson_lower_bound(0, 50) == 0.0
    assert wilson_lower_bound(0, 0) == 0.0


def test_bound_grows_with_evidence_at_a_fixed_rate():
    bounds = [wilson_lower_bound(n // 2, n) for n in (2, 10, 100, 1000)]
    assert bounds == sorted(bounds)
    assert bounds[-1] < 0.5


@pytest.mark.parametrize(("failures", "trials"), [(-1, 10), (11, 10)])
def test_impossible_counts_are_rejected(failures, trials):
    with pytest.raises(ValueError):
        wilson_lower_bound(failures, trials)
