"""Run history in SQLite.

The analysis needs one access pattern: every execution of each test, in time order. The
schema is shaped for exactly that (an index on results.test_id, runs ordered by
created_at). dynamo.py serves the same pattern from DynamoDB for the serverless backend.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from .model import CaseResult, Execution, Outcome, Run

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    commit_sha  TEXT NOT NULL,
    branch      TEXT,
    created_at  TEXT NOT NULL            -- ISO-8601 UTC, so text order is time order
);
CREATE TABLE IF NOT EXISTS results (
    run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    test_id     TEXT NOT NULL,
    attempt     INTEGER NOT NULL,
    outcome     TEXT NOT NULL,
    duration_s  REAL NOT NULL,
    message     TEXT,
    PRIMARY KEY (run_id, test_id, attempt)
);
CREATE INDEX IF NOT EXISTS results_by_test ON results(test_id);
CREATE INDEX IF NOT EXISTS runs_by_commit ON runs(commit_sha);
"""


class StoreError(ValueError):
    pass


class RunConflictError(StoreError):
    """A run id was reused for a different commit."""


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add_run(self, run: Run, results: Iterable[CaseResult]) -> int:
        """Record results for a run. Safe to repeat, and safe to call once per shard.

        Rows are keyed by (run_id, test_id, attempt): uploading the same report twice
        overwrites rather than double-counts, and a run split across several CI shards
        (several reports, one run_id) accumulates.
        """
        rows = [(run.run_id, r.test_id, r.attempt, r.outcome.value, r.duration_s, r.message)
                for r in results]
        with self._db:  # one transaction: a half-ingested report never becomes visible
            self._db.execute(
                "INSERT OR IGNORE INTO runs (run_id, commit_sha, branch, created_at)"
                " VALUES (?, ?, ?, ?)",
                (run.run_id, run.commit, run.branch, _to_text(run.created_at)),
            )
            (stored_commit,) = self._db.execute(
                "SELECT commit_sha FROM runs WHERE run_id = ?", (run.run_id,)).fetchone()
            if stored_commit != run.commit:
                # A reused run id would silently merge two commits' results, manufacturing
                # (or hiding) exactly the pass/fail mix the analysis treats as flakiness.
                raise RunConflictError(f"run {run.run_id!r} is already recorded for commit "
                                 f"{stored_commit}, not {run.commit}")
            self._db.executemany(
                "INSERT OR REPLACE INTO results"
                " (run_id, test_id, attempt, outcome, duration_s, message)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def executions(self) -> Iterator[Execution]:
        """Every recorded attempt, grouped by test and in time order within each test."""
        cursor = self._db.execute(
            "SELECT r.test_id, r.outcome, r.attempt, r.duration_s, r.message,"
            "       runs.run_id, runs.commit_sha, runs.created_at"
            " FROM results AS r JOIN runs USING (run_id)"
            " ORDER BY r.test_id, runs.created_at, runs.run_id, r.attempt"
        )
        for test_id, outcome, attempt, duration, message, run_id, commit, created in cursor:
            yield Execution(test_id, Outcome(outcome), attempt, duration, message, run_id,
                            commit, datetime.fromisoformat(created))

    def run_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def _to_text(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise StoreError("created_at must be timezone-aware")
    return moment.astimezone(UTC).isoformat(timespec="microseconds")
