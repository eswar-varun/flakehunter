"""Classify every test from its execution history.

The core rule: **a test that both passed and failed on the same commit is flaky.** The code
didn't change, so the outcome came from something the test doesn't control: timing,
ordering, randomness, shared state, the network. That evidence is close to certain, which
keeps false alarms low. Other patterns are weaker evidence and get weaker labels.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby
from operator import attrgetter

from .model import Execution, Outcome
from .stats import wilson_lower_bound


class Status(StrEnum):
    FLAKY = "flaky"  # passed and failed on the same commit
    BROKEN = "broken"  # failed every attempt on the latest commit it ran on
    SUSPECT = "suspect"  # failed intermittently across commits, never on the same commit
    STABLE = "stable"
    SKIPPED = "skipped"  # never actually ran


# Report order: what needs a human first.
_PRIORITY = {Status.BROKEN: 0, Status.FLAKY: 1, Status.SUSPECT: 2, Status.STABLE: 3,
             Status.SKIPPED: 4}


@dataclass(frozen=True, slots=True)
class Verdict:
    test_id: str
    status: Status
    executions: int  # attempts that actually ran (skips excluded)
    failures: int
    commits: int
    flaky_commits: int  # commits on which the test both passed and failed
    score: float  # Wilson lower bound of the failure rate: rank within a status
    last_failure: str | None

    @property
    def failure_rate(self) -> float:
        return self.failures / self.executions if self.executions else 0.0


def analyze(executions: Iterable[Execution]) -> list[Verdict]:
    """Verdicts for every test, most urgent first.

    `executions` must be grouped by test_id and time-ordered within each test, which is
    what Store.executions() returns. Grouping lets this run in one streaming pass holding
    only one test's history in memory at a time.
    """
    verdicts: list[Verdict] = []
    seen: set[str] = set()
    for test_id, group in groupby(executions, key=attrgetter("test_id")):
        if test_id in seen:
            raise ValueError(f"executions are not grouped by test_id ({test_id!r} reappears)")
        seen.add(test_id)
        verdicts.append(_verdict(test_id, list(group)))
    verdicts.sort(key=lambda v: (_PRIORITY[v.status], -v.score, v.test_id))
    return verdicts


def _verdict(test_id: str, history: list[Execution]) -> Verdict:
    ran = [e for e in history if e.outcome is not Outcome.SKIPPED]
    if not ran:
        return Verdict(test_id, Status.SKIPPED, 0, 0, 0, 0, 0.0, None)

    # commit -> [passes, failures]. A dict, not a sort: one O(1) update per execution, and
    # insertion order preserves "first seen", which is chronological here.
    per_commit: dict[str, list[int]] = {}
    for e in ran:
        per_commit.setdefault(e.commit, [0, 0])[e.outcome.is_failure] += 1

    failures = sum(fails for _, fails in per_commit.values())
    flaky_commits = sum(1 for passes, fails in per_commit.values() if passes and fails)
    latest_passes, latest_failures = per_commit[ran[-1].commit]

    if flaky_commits:
        status = Status.FLAKY
    elif latest_passes == 0:
        # Checked before SUSPECT on purpose: if a test with an intermittent past fails on
        # the newest commit, assume a real regression until proven otherwise. Calling it
        # "probably flaky" is how real bugs get ignored.
        status = Status.BROKEN
    elif _failure_episodes(ran) >= 2:
        status = Status.SUSPECT
    else:
        # Includes "failed on old commits, passes now": a regression that was fixed.
        status = Status.STABLE

    last_failure = next((e.message for e in reversed(ran) if e.outcome.is_failure), None)
    return Verdict(test_id, status, len(ran), failures, len(per_commit), flaky_commits,
                   wilson_lower_bound(failures, len(ran)), last_failure)


def _failure_episodes(ran: list[Execution]) -> int:
    """Number of separate stretches of consecutive failures (fail, pass, fail = 2)."""
    episodes, previous_failed = 0, False
    for e in ran:
        failed = e.outcome.is_failure
        if failed and not previous_failed:
            episodes += 1
        previous_failed = failed
    return episodes
