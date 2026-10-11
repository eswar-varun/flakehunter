from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flakehunter.model import Execution, Outcome

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def execution(test_id: str, outcome: str, commit: str, minute: int, attempt: int = 0,
              message: str | None = None) -> Execution:
    return Execution(test_id, Outcome(outcome), attempt, 0.0, message, f"run-{minute}", commit,
                     T0 + timedelta(minutes=minute))
