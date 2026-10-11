from __future__ import annotations

import json

import pytest

from flakehunter.cli import main

GITHUB_VARS = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REF_NAME")


def _report(path, outcomes: dict[str, str]):
    cases = []
    for name, outcome in outcomes.items():
        body = {"passed": "", "failed": "<failure message='boom'/>",
                "skipped": "<skipped/>"}[outcome]
        cases.append(f"<testcase classname='suite' name='{name}'>{body}</testcase>")
    path.write_text(f"<testsuite>{''.join(cases)}</testsuite>", encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def outside_github(monkeypatch):
    for var in GITHUB_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("FLAKEHUNTER_DB", raising=False)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "history.db")


def _ingest(db, report, run_id, commit, minute):
    return main(["--db", db, "ingest", report, "--run-id", run_id, "--commit", commit,
                 "--created-at", f"2026-01-01T00:{minute:02d}:00+00:00"])


def test_ingest_then_report_end_to_end(tmp_path, db, capsys):
    _ingest(db, _report(tmp_path / "1.xml", {"a": "passed", "b": "passed", "c": "failed"}),
            "r1", "c1", 1)
    _ingest(db, _report(tmp_path / "2.xml", {"a": "failed", "b": "passed", "c": "failed"}),
            "r2", "c1", 2)
    capsys.readouterr()

    assert main(["--db", db, "report", "--format", "json"]) == 0
    verdicts = {v["test_id"]: v for v in json.loads(capsys.readouterr().out)}

    assert verdicts["suite::a"]["status"] == "flaky"
    assert verdicts["suite::c"]["status"] == "broken"
    assert "suite::b" not in verdicts  # stable tests are hidden by default


def test_all_flag_includes_stable_tests(tmp_path, db, capsys):
    _ingest(db, _report(tmp_path / "1.xml", {"a": "passed"}), "r1", "c1", 1)
    capsys.readouterr()

    main(["--db", db, "report", "--all", "--format", "json"])

    assert json.loads(capsys.readouterr().out)[0]["status"] == "stable"


def test_markdown_report_has_a_table(tmp_path, db, capsys):
    _ingest(db, _report(tmp_path / "1.xml", {"x|y": "failed"}), "r1", "c1", 1)
    capsys.readouterr()

    main(["--db", db, "report", "--format", "markdown"])

    out = capsys.readouterr().out
    assert "| status | score |" in out
    assert "`suite::x\\|y`" in out  # a pipe in a test id must not break the table


def test_github_actions_environment_supplies_run_and_commit(tmp_path, db, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_RUN_ID", "7")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_SHA", "deadbeefcafe0000")

    assert main(["--db", db, "ingest", _report(tmp_path / "1.xml", {"a": "passed"})]) == 0
    assert "run 7-2 @ deadbeefcafe" in capsys.readouterr().out


def test_ingest_outside_github_requires_a_commit(tmp_path, db):
    with pytest.raises(SystemExit) as exit_info:
        main(["--db", db, "ingest", _report(tmp_path / "1.xml", {"a": "passed"}),
              "--run-id", "r1"])
    assert exit_info.value.code == 2


def test_glob_patterns_collect_all_shards(tmp_path, db, capsys):
    shards = tmp_path / "reports"
    shards.mkdir()
    _report(shards / "shard-1.xml", {"a": "passed"})
    _report(shards / "shard-2.xml", {"b": "passed"})

    main(["--db", db, "ingest", str(shards / "*.xml"), "--run-id", "r1", "--commit", "c1"])

    assert "recorded 2 results from 2 report(s)" in capsys.readouterr().out


def test_unparseable_report_exits_1_with_a_message(tmp_path, db, capsys):
    bad = tmp_path / "bad.xml"
    bad.write_text("<html/>", encoding="utf-8")

    assert main(["--db", db, "ingest", str(bad), "--run-id", "r1", "--commit", "c1"]) == 1
    assert "not a JUnit report" in capsys.readouterr().err
