"""HTTP API for the serverless backend: one Lambda function behind API Gateway (HTTP API,
payload format 2.0).

    POST /projects/{project}/runs?run_id=&commit=[&branch=&created_at=]    body: JUnit XML
    GET  /projects/{project}/verdicts[?all=true]
    GET  /projects/{project}/history?test_id=

Uploads need `Authorization: Bearer <token>`; reads are public, like the CLI's report.
The handler only talks to a store through add_run / executions / run_count, so the same code
runs against DynamoDB in Lambda and against a local emulator in development.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
import os
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .analysis import Status, analyze
from .junit import JUnitParseError, parse_string
from .model import Run
from .report import as_dict
from .store import RunConflictError, StoreError

log = logging.getLogger(__name__)

# Lambda's synchronous payload limit is 6 MB, and base64 adds a third; refuse before parsing.
MAX_BODY_BYTES = 4 * 1024 * 1024
SECRET_TTL_S = 300

# API Gateway route keys; the CDK stack declares the same three.
UPLOAD = "POST /projects/{project}/runs"
VERDICTS = "GET /projects/{project}/verdicts"
HISTORY = "GET /projects/{project}/history"
ROUTE_KEYS = (UPLOAD, VERDICTS, HISTORY)

Event = dict[str, Any]
Response = dict[str, Any]


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def make_handler(store: Any, token: Callable[[], str]) -> Callable[[Event, Any], Response]:
    """Build the Lambda handler around a store and a source for the upload token."""
    routes: dict[str, Callable[[Event], tuple[int, dict[str, Any]]]] = {
        UPLOAD: lambda e: _upload(e, store, token),
        VERDICTS: lambda e: _verdicts(e, store),
        HISTORY: lambda e: _history(e, store),
    }

    def handler(event: Event, context: Any) -> Response:
        started = time.perf_counter()
        route = event.get("routeKey", "")
        try:
            if route not in routes:
                raise HttpError(404, f"no route for {route}")
            status, body = routes[route](event)
        except HttpError as exc:
            status, body = exc.status, {"error": str(exc)}
        except JUnitParseError as exc:
            status, body = 400, {"error": str(exc)}
        except RunConflictError as exc:
            status, body = 409, {"error": str(exc)}
        except StoreError as exc:
            status, body = 400, {"error": str(exc)}
        except Exception:
            # The traceback goes to the logs; the caller learns only that it wasn't their fault.
            log.exception("unhandled error on %s", route)
            status, body = 500, {"error": "internal error"}
        log.info(json.dumps({
            "request_id": event.get("requestContext", {}).get("requestId"),
            "route": route,
            "project": (event.get("pathParameters") or {}).get("project"),
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }))
        return {"statusCode": status, "headers": {"content-type": "application/json"},
                "body": json.dumps(body)}

    return handler


def _upload(event: Event, store: Any, token: Callable[[], str]) -> tuple[int, dict[str, Any]]:
    _authorize(event, token)
    project = _project(event)
    params = event.get("queryStringParameters") or {}
    for name in ("run_id", "commit"):
        if not params.get(name):
            raise HttpError(400, f"query parameter {name} is required")
    raw = _body(event)
    results = parse_string(raw)
    run = Run(params["run_id"], params["commit"], _created_at(params.get("created_at")),
              params.get("branch") or None)
    recorded = store.add_run(project, run, results)
    return 201, {"project": project, "run_id": run.run_id, "recorded": recorded}


def _verdicts(event: Event, store: Any) -> tuple[int, dict[str, Any]]:
    project = _project(event)
    params = event.get("queryStringParameters") or {}
    verdicts = analyze(store.executions(project))
    counts = Counter(v.status.value for v in verdicts)
    if params.get("all") != "true":
        verdicts = [v for v in verdicts if v.status not in (Status.STABLE, Status.SKIPPED)]
    return 200, {
        "project": project,
        "runs": store.run_count(project),
        "summary": {s.value: counts[s.value] for s in Status},
        "verdicts": [as_dict(v) for v in verdicts],
    }


def _history(event: Event, store: Any) -> tuple[int, dict[str, Any]]:
    project = _project(event)
    test_id = (event.get("queryStringParameters") or {}).get("test_id")
    if not test_id:
        raise HttpError(400, "query parameter test_id is required")
    executions = list(store.executions(project, test_id=test_id))
    [verdict] = analyze(executions) or [None]
    return 200, {
        "project": project,
        "test_id": test_id,
        "verdict": as_dict(verdict) if verdict else None,
        "executions": [{
            "run_id": e.run_id,
            "commit": e.commit,
            "created_at": e.created_at.isoformat(),
            "attempt": e.attempt,
            "outcome": e.outcome.value,
            "duration_s": e.duration_s,
            "message": e.message,
        } for e in executions],
    }


def _authorize(event: Event, token: Callable[[], str]) -> None:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    scheme, _, given = headers.get("authorization", "").partition(" ")
    # Constant-time comparison, so response timing doesn't leak how much of a guess was right.
    if scheme.lower() != "bearer" or not hmac.compare_digest(given.encode(), token().encode()):
        raise HttpError(401, "missing or invalid bearer token")


def _project(event: Event) -> str:
    return (event.get("pathParameters") or {}).get("project", "")


def _body(event: Event) -> bytes:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        if len(body) > MAX_BODY_BYTES * 4 // 3 + 4:
            raise HttpError(413, f"report is larger than {MAX_BODY_BYTES} bytes")
        try:
            raw = base64.b64decode(body, validate=True)
        except binascii.Error as exc:
            raise HttpError(400, "body is not valid base64") from exc
    else:
        raw = body.encode()
    if len(raw) > MAX_BODY_BYTES:
        raise HttpError(413, f"report is larger than {MAX_BODY_BYTES} bytes")
    return raw


def _created_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HttpError(400, f"created_at is not an ISO 8601 time: {value!r}") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _secret_token(secret_arn: str) -> Callable[[], str]:
    """The upload token from Secrets Manager, cached so most requests skip the call.

    The cache expires, so a rotated secret takes effect within SECRET_TTL_S.
    """
    import boto3

    client = boto3.client("secretsmanager")
    cached: dict[str, Any] = {"value": None, "at": 0.0}

    def token() -> str:
        if cached["value"] is None or time.monotonic() - cached["at"] > SECRET_TTL_S:
            cached["value"] = client.get_secret_value(SecretId=secret_arn)["SecretString"]
            cached["at"] = time.monotonic()
        return cached["value"]

    return token


_lambda_handler: Callable[[Event, Any], Response] | None = None


def handler(event: Event, context: Any) -> Response:
    """Lambda entry point. Built on first use, so cold starts pay for setup once."""
    global _lambda_handler
    if _lambda_handler is None:
        from .dynamo import DynamoStore

        log.setLevel(logging.INFO)
        _lambda_handler = make_handler(DynamoStore(os.environ["TABLE_NAME"]),
                                       _secret_token(os.environ["TOKEN_SECRET_ARN"]))
    return _lambda_handler(event, context)
