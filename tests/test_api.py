from __future__ import annotations

import base64
import json
import logging

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from flakehunter.api import MAX_BODY_BYTES, make_handler  # noqa: E402
from flakehunter.dynamo import DynamoStore, create_table  # noqa: E402

TOKEN = "s3cret-token"


def junit(**cases: str) -> str:
    """JUnit XML with one <testcase> per keyword: passed, failed or flaky (failed, then passed)."""
    body = {
        "passed": "",
        "failed": '<failure message="boom">trace</failure>',
        "flaky": '<flakyFailure message="first try failed">trace</flakyFailure>',
    }
    rows = "".join(f'<testcase classname="t" name="{name}" time="0.1">{body[kind]}</testcase>'
                   for name, kind in cases.items())
    return f'<testsuite name="s">{rows}</testsuite>'


def event(route: str, project: str = "demo", query: dict | None = None, body: str | None = None,
          token: str | None = TOKEN, b64: bool = False) -> dict:
    method = route.split(" ", 1)[0]
    if b64 and body is not None:
        body = base64.b64encode(body.encode()).decode()
    return {
        "version": "2.0",
        "routeKey": route,
        "pathParameters": {"project": project},
        "queryStringParameters": query,
        "headers": {"authorization": f"Bearer {token}"} if token else {},
        "body": body,
        "isBase64Encoded": b64,
        "requestContext": {"requestId": "req-1", "http": {"method": method}},
    }


def upload(handler, xml: str, run_id: str, commit: str = "c1", **kwargs) -> dict:
    query = {"run_id": run_id, "commit": commit, "created_at": f"2026-01-01T00:0{run_id[-1]}:00Z"}
    return handler(event("POST /projects/{project}/runs", query=query, body=xml, **kwargs), None)


def payload(response: dict) -> dict:
    assert response["headers"]["content-type"] == "application/json"
    return json.loads(response["body"])


@pytest.fixture
def store():
    with moto.mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_table(client, "flakehunter-test")
        yield DynamoStore("flakehunter-test", client=client)


@pytest.fixture
def handler(store):
    return make_handler(store, token=lambda: TOKEN)


def test_upload_then_report_finds_the_flaky_test(handler):
    assert upload(handler, junit(test_ok="passed", test_flip="failed"), "r1")["statusCode"] == 201
    assert upload(handler, junit(test_ok="passed", test_flip="passed"), "r2")["statusCode"] == 201

    response = handler(event("GET /projects/{project}/verdicts", token=None), None)

    assert response["statusCode"] == 200
    body = payload(response)
    assert body["project"] == "demo"
    assert body["runs"] == 2
    assert [(v["test_id"], v["status"]) for v in body["verdicts"]] == [("t::test_flip", "flaky")]


def test_upload_reports_how_many_results_were_recorded(handler):
    body = payload(upload(handler, junit(a="passed", b="flaky"), "r1"))

    assert body == {"project": "demo", "run_id": "r1", "recorded": 3}


def test_all_includes_stable_tests(handler):
    upload(handler, junit(test_ok="passed"), "r1")

    default = payload(handler(event("GET /projects/{project}/verdicts"), None))
    everything = payload(handler(event("GET /projects/{project}/verdicts",
                                       query={"all": "true"}), None))

    assert default["verdicts"] == []
    assert [v["status"] for v in everything["verdicts"]] == ["stable"]


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_uploads_need_the_token(handler, store, token):
    response = upload(handler, junit(a="failed"), "r1", token=token)

    assert response["statusCode"] == 401
    assert list(store.executions("demo")) == []


@pytest.mark.parametrize("missing", ["run_id", "commit"])
def test_uploads_need_a_run_id_and_commit(handler, missing):
    query = {"run_id": "r1", "commit": "c1"}
    del query[missing]

    response = handler(event("POST /projects/{project}/runs", query=query,
                             body=junit(a="passed")), None)

    assert response["statusCode"] == 400
    assert missing in payload(response)["error"]


def test_reports_that_are_not_junit_are_rejected(handler):
    response = upload(handler, "<html><body>not a report</body></html>", "r1")

    assert response["statusCode"] == 400
    assert "not a JUnit report" in payload(response)["error"]


def test_entity_expansion_attacks_are_rejected(handler):
    bomb = ('<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><testsuite>&b;</testsuite>')

    assert upload(handler, bomb, "r1")["statusCode"] == 400


def test_reusing_a_run_id_for_another_commit_is_a_conflict(handler):
    upload(handler, junit(a="passed"), "r1", commit="c1")

    response = upload(handler, junit(a="failed"), "r1", commit="c2")

    assert response["statusCode"] == 409
    assert "already recorded for commit c1" in payload(response)["error"]


def test_base64_bodies_are_decoded(handler):
    # API Gateway base64-encodes bodies whose content type it treats as binary.
    response = upload(handler, junit(a="passed"), "r1", b64=True)

    assert response["statusCode"] == 201


def test_oversized_bodies_are_rejected_before_parsing(handler):
    response = upload(handler, "x" * (MAX_BODY_BYTES + 1), "r1")

    assert response["statusCode"] == 413


def test_invalid_project_names_are_rejected(handler):
    response = handler(event("GET /projects/{project}/verdicts", project="has space"), None)

    assert response["statusCode"] == 400


def test_history_returns_one_tests_executions_in_time_order(handler):
    upload(handler, junit(test_flip="failed"), "r1")
    upload(handler, junit(test_flip="passed"), "r2")

    body = payload(handler(event("GET /projects/{project}/history",
                                 query={"test_id": "t::test_flip"}), None))

    assert body["test_id"] == "t::test_flip"
    assert [(e["run_id"], e["outcome"]) for e in body["executions"]] == [
        ("r1", "failed"), ("r2", "passed")]
    assert body["verdict"]["status"] == "flaky"


def test_history_of_an_unknown_test_is_empty(handler):
    body = payload(handler(event("GET /projects/{project}/history",
                                 query={"test_id": "t::nope"}), None))

    assert body["executions"] == []
    assert body["verdict"] is None


def test_history_needs_a_test_id(handler):
    response = handler(event("GET /projects/{project}/history"), None)

    assert response["statusCode"] == 400


def test_unknown_routes_are_404(handler):
    assert handler(event("DELETE /projects/{project}"), None)["statusCode"] == 404


def test_unexpected_errors_are_500_without_internals(store, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("database password is hunter2")

    store.executions = broken
    handler = make_handler(store, token=lambda: TOKEN)

    response = handler(event("GET /projects/{project}/verdicts"), None)

    assert response["statusCode"] == 500
    assert "hunter2" not in response["body"]


def test_every_request_logs_one_json_line(handler, caplog):
    with caplog.at_level(logging.INFO, logger="flakehunter.api"):
        upload(handler, junit(a="passed"), "r1")

    [record] = [r for r in caplog.records if r.name == "flakehunter.api"]
    line = json.loads(record.getMessage())
    assert line["request_id"] == "req-1"
    assert line["route"] == "POST /projects/{project}/runs"
    assert line["status"] == 201
    assert isinstance(line["duration_ms"], float)
