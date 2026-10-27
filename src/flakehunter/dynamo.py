"""Run history in DynamoDB, for the serverless backend.

One table, one partition per project. The analysis needs every execution grouped by test and
time-ordered within each test, so that is exactly the order of the sort key:

    pk = PROJECT#<project>
    sk = RESULT#<test_id> SEP <created_at> SEP <run_id> SEP <attempt>     one attempt of one test
    sk = RUN#<run_id>                                                     the run's commit and time

One paginated Query on the partition streams results straight into analysis.analyze(), and
`begins_with(sk, "RESULT#<test_id>" SEP)` returns a single test's history. SEP is the ASCII
unit separator (U+001F). XML 1.0 can't contain it, so no test id from a JUnit report does,
which makes "t::a" SEP an exact prefix: it can't also match "t::ab" or "t::a[1]".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from itertools import groupby
from operator import attrgetter
from typing import Any

from .model import CaseResult, Execution, Outcome, Run
from .store import RunConflictError, StoreError

SEP = "\x1f"
# DynamoDB's limit on actions in one TransactWriteItems call.
MAX_TRANSACTION_ITEMS = 100

_PROJECT = re.compile(r"[A-Za-z0-9._-]{1,100}")
_RUN_ID = re.compile(r"[A-Za-z0-9._:/-]{1,128}")
_COMMIT = re.compile(r"[A-Za-z0-9._/-]{1,128}")


def create_table(client: Any, name: str) -> None:
    """The table the CDK stack defines, for tests and local development."""
    client.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


class DynamoStore:
    def __init__(self, table_name: str, client: Any = None) -> None:
        if client is None:
            import boto3  # Lambda's runtime ships boto3; the CLI never needs it.
            from botocore.config import Config

            client = boto3.client("dynamodb", config=Config(retries={"mode": "standard"}))
        self._client = client
        self._table = table_name

    def add_run(self, project: str, run: Run, results: Iterable[CaseResult]) -> int:
        """Record results for a run. Safe to repeat, and safe to call once per shard.

        Same guarantees as the SQLite store: a repeated upload overwrites instead of
        double-counting, shards of one run accumulate, and a run id reused for a different
        commit is refused.
        """
        _check(_PROJECT, project, "project")
        _check(_RUN_ID, run.run_id, "run_id")
        _check(_COMMIT, run.commit, "commit")
        # The same (test, attempt) twice in one report would be two writes to one item, which
        # a transaction refuses; keep the last, as the SQLite store's INSERT OR REPLACE does.
        results = list({(r.test_id, r.attempt): r for r in results}.values())
        for result in results:
            if SEP in result.test_id:
                raise StoreError(f"test id contains a control character: {result.test_id!r}")
        created_at = self._claim_run(project, run)
        for chunk in _transactions(results):
            self._client.transact_write_items(TransactItems=[
                {"Put": {"TableName": self._table,
                         "Item": _result_item(project, run, created_at, r)}}
                for r in chunk])
        return len(results)

    def executions(self, project: str, test_id: str | None = None) -> Iterator[Execution]:
        """Every recorded attempt, grouped by test and in time order within each test.

        With `test_id`, only that test's history.
        """
        _check(_PROJECT, project, "project")
        prefix = "RESULT#" if test_id is None else f"RESULT#{test_id}{SEP}"
        for item in self._query(project, prefix):
            yield Execution(
                test_id=item["test_id"]["S"],
                outcome=Outcome(item["outcome"]["S"]),
                attempt=int(item["attempt"]["N"]),
                duration_s=float(item["duration_s"]["N"]),
                message=item["message"]["S"] if "message" in item else None,
                run_id=item["run_id"]["S"],
                commit=item["commit_sha"]["S"],
                created_at=datetime.fromisoformat(item["created_at"]["S"]),
            )

    def run_count(self, project: str) -> int:
        _check(_PROJECT, project, "project")
        pages = self._client.get_paginator("query").paginate(
            TableName=self._table, Select="COUNT", **_key_condition(project, "RUN#"))
        return sum(page["Count"] for page in pages)

    def _claim_run(self, project: str, run: Run) -> str:
        """Record the run, or confirm it was already recorded for the same commit.

        Returns the run's recorded time. Result keys contain it, so a retried upload stamped
        with a later time still lands on the same keys and overwrites.
        """
        try:
            response = self._client.update_item(
                TableName=self._table,
                Key={"pk": {"S": _pk(project)}, "sk": {"S": f"RUN#{run.run_id}"}},
                UpdateExpression="SET commit_sha = if_not_exists(commit_sha, :commit), "
                                 "created_at = if_not_exists(created_at, :created), "
                                 "branch = if_not_exists(branch, :branch)",
                # The condition makes claim-or-confirm one atomic step, so two uploads racing
                # with the same run id and different commits can't both succeed.
                ConditionExpression="attribute_not_exists(pk) OR commit_sha = :commit",
                ExpressionAttributeValues={
                    ":commit": {"S": run.commit},
                    ":created": {"S": _to_text(run.created_at)},
                    ":branch": {"S": run.branch} if run.branch else {"NULL": True},
                },
                ReturnValues="ALL_NEW",
                ReturnValuesOnConditionCheckFailure="ALL_OLD",
            )
        except self._client.exceptions.ConditionalCheckFailedException as exc:
            stored = exc.response.get("Item", {}).get("commit_sha", {}).get("S")
            if stored is None:  # older APIs and emulators don't return the item
                stored = self._client.get_item(
                    TableName=self._table, ConsistentRead=True,
                    Key={"pk": {"S": _pk(project)}, "sk": {"S": f"RUN#{run.run_id}"}},
                )["Item"]["commit_sha"]["S"]
            # A reused run id would silently merge two commits' results, manufacturing (or
            # hiding) exactly the pass/fail mix the analysis treats as flakiness.
            raise RunConflictError(f"run {run.run_id!r} is already recorded for commit {stored}, "
                             f"not {run.commit}") from exc
        return response["Attributes"]["created_at"]["S"]

    def _query(self, project: str, prefix: str) -> Iterator[dict[str, Any]]:
        pages = self._client.get_paginator("query").paginate(
            TableName=self._table, **_key_condition(project, prefix))
        for page in pages:
            yield from page["Items"]


def _transactions(results: list[CaseResult]) -> Iterator[list[CaseResult]]:
    """Batches of at most MAX_TRANSACTION_ITEMS that never split one test's attempts.

    Each batch is written atomically, so a crash between batches can leave some tests
    recorded and others not (each recorded result is still a true observation, and the
    retry fills in the rest), but never a failed attempt without the retry that passed.
    """
    chunk: list[CaseResult] = []
    ordered = sorted(results, key=attrgetter("test_id"))
    for _, attempts in groupby(ordered, key=attrgetter("test_id")):
        attempts = list(attempts)
        if chunk and len(chunk) + len(attempts) > MAX_TRANSACTION_ITEMS:
            yield chunk
            chunk = []
        # A single test with over 100 attempts in one run can't be atomic; split it.
        while len(attempts) > MAX_TRANSACTION_ITEMS:
            yield attempts[:MAX_TRANSACTION_ITEMS]
            attempts = attempts[MAX_TRANSACTION_ITEMS:]
        chunk.extend(attempts)
    if chunk:
        yield chunk


def _result_item(project: str, run: Run, created_at: str, r: CaseResult) -> dict[str, Any]:
    item = {
        "pk": {"S": _pk(project)},
        # Attempts are zero-padded so "10" sorts after "9".
        "sk": {"S": f"RESULT#{r.test_id}{SEP}{created_at}{SEP}{run.run_id}{SEP}{r.attempt:04d}"},
        "test_id": {"S": r.test_id},
        "outcome": {"S": r.outcome.value},
        "attempt": {"N": str(r.attempt)},
        "duration_s": {"N": repr(r.duration_s)},
        "run_id": {"S": run.run_id},
        "commit_sha": {"S": run.commit},
        "created_at": {"S": created_at},
    }
    if r.message:
        item["message"] = {"S": r.message}
    return item


def _key_condition(project: str, prefix: str) -> dict[str, Any]:
    return {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": {"S": _pk(project)}, ":prefix": {"S": prefix}},
    }


def _pk(project: str) -> str:
    return f"PROJECT#{project}"


def _check(pattern: re.Pattern[str], value: str, name: str) -> None:
    if not pattern.fullmatch(value):
        raise StoreError(f"invalid {name}: {value!r}")


def _to_text(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise StoreError("created_at must be timezone-aware")
    # Fixed width and UTC, so text order in the sort key is time order.
    return moment.astimezone(UTC).isoformat(timespec="microseconds")
