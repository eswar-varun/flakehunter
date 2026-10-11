"""A zoo of tests with known behaviour, used to measure FlakeHunter's detection.

Each test's name prefix is its ground-truth label:
    test_stable_*   always passes
    test_flaky_*    sometimes fails on the same code (the kind FlakeHunter must catch)
    test_broken_*   always fails (must be reported as broken, never as flaky)
    test_skipped_*  never runs

The flaky ones reproduce the root causes seen most often in real suites: randomness,
timing assumptions, async ordering assumptions, and state leaking between tests.
"""

import asyncio
import random
import threading

import pytest

# --- stable -------------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(10))
def test_stable_arithmetic(n):
    assert n + n == 2 * n


def test_stable_sorting():
    assert sorted([3, 1, 2]) == [1, 2, 3]


def test_stable_dict_round_trip():
    data = {"a": 1, "b": 2}
    assert dict(data.items()) == data


# --- flaky: randomness ------------------------------------------------------------------


def test_flaky_random_30pct():
    assert random.random() >= 0.30


def test_flaky_random_10pct():
    assert random.random() >= 0.10


def test_flaky_random_3pct():
    # Rare on purpose: shows how many runs a low-rate flake needs before anyone sees it.
    assert random.random() >= 0.03


# --- flaky: timing ----------------------------------------------------------------------


def test_flaky_timing_worker_timeout():
    # Waits 40 ms for a worker that takes 0-50 ms: fine on a fast run, fails on a slow one.
    done = threading.Event()
    worker = threading.Timer(random.uniform(0, 0.05), done.set)
    worker.start()
    try:
        assert done.wait(timeout=0.04)
    finally:
        worker.cancel()


# --- flaky: async ordering assumption ------------------------------------------------------


def test_flaky_async_completion_order():
    async def job(name, finished):
        await asyncio.sleep(random.uniform(0, 0.01))
        finished.append(name)

    async def main():
        finished = []
        await asyncio.gather(job("a", finished), job("b", finished))
        return finished

    # Assumes "a" finishes first because it started first. Nothing guarantees that.
    assert asyncio.run(main()) == ["a", "b"]


# --- flaky: order dependence (state leaking between tests) --------------------------------

_CACHE: dict[str, str] = {}


def test_stable_order_polluter():
    # Passes every time, but leaves state behind and never cleans it up.
    _CACHE["user"] = "alice"
    assert _CACHE["user"] == "alice"


def test_flaky_order_victim():
    # Fails whenever the polluter happened to run first.
    assert "user" not in _CACHE


# --- broken -------------------------------------------------------------------------------


def test_broken_off_by_one():
    assert sum(range(10)) == 46


def test_broken_wrong_exception():
    with pytest.raises(KeyError):
        [1, 2, 3][10]  # raises IndexError, not KeyError


@pytest.fixture
def unavailable_database():
    raise ConnectionError("database unavailable")


def test_broken_fixture_error(unavailable_database):
    pass


# --- skipped ------------------------------------------------------------------------------


@pytest.mark.skip(reason="not supported on this platform")
def test_skipped_platform_specific():
    pass
