from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"  # an assertion failed
    ERROR = "error"  # broke outside the assertion: fixture, setup, crash
    SKIPPED = "skipped"

    @property
    def is_failure(self) -> bool:
        return self in (Outcome.FAILED, Outcome.ERROR)


@dataclass(frozen=True, slots=True)
class CaseResult:
    """One attempt at one test case, as parsed from a report.

    `attempt` counts retries within a single CI run (0 = first try). Runners that retry
    failing tests (Surefire's rerunFailingTestsCount, pytest-rerunfailures) produce several
    attempts for one test in one run, and those are the cheapest evidence of flakiness.
    """

    test_id: str
    outcome: Outcome
    duration_s: float = 0.0
    attempt: int = 0
    message: str | None = None


@dataclass(frozen=True, slots=True)
class Run:
    """One CI execution of a test suite against one commit."""

    run_id: str
    commit: str
    created_at: datetime
    branch: str | None = None


@dataclass(frozen=True, slots=True)
class Execution:
    """A CaseResult joined with the run it belongs to, as read back from the store."""

    test_id: str
    outcome: Outcome
    attempt: int
    duration_s: float
    message: str | None
    run_id: str
    commit: str
    created_at: datetime
