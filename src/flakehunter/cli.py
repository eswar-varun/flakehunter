"""Command line: `flakehunter ingest` after each CI run, `flakehunter report` to triage."""

from __future__ import annotations

import argparse
import glob
import os
import sys
from datetime import UTC, datetime

from . import __version__, report
from .analysis import Status, analyze
from .junit import JUnitParseError, parse_file
from .model import Run
from .store import Store, StoreError

DEFAULT_DB = ".flakehunter.db"


def _default_run_id() -> str | None:
    # GitHub re-runs keep GITHUB_RUN_ID and bump the attempt; each attempt is its own run,
    # which is exactly what makes "re-run failed jobs" useful flakiness evidence.
    run_id = os.environ.get("GITHUB_RUN_ID")
    return f"{run_id}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if run_id else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flakehunter", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--db", default=os.environ.get("FLAKEHUNTER_DB", DEFAULT_DB),
                        help=f"SQLite history file (default: $FLAKEHUNTER_DB or {DEFAULT_DB})")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="record one CI run's JUnit XML report(s)")
    ingest.add_argument("reports", nargs="+", help="JUnit XML files or glob patterns")
    ingest.add_argument("--run-id", default=_default_run_id(),
                        help="unique id of this CI run (default: GitHub run id + attempt)")
    ingest.add_argument("--commit", default=os.environ.get("GITHUB_SHA"),
                        help="commit under test (default: $GITHUB_SHA)")
    ingest.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME"))
    ingest.add_argument("--created-at", type=datetime.fromisoformat, default=None,
                        help="ISO timestamp of the run, for backfills (default: now)")

    show = commands.add_parser("report", help="classify every test and print the result")
    show.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    show.add_argument("--all", action="store_true", help="include stable and skipped tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            return _ingest(args, parser)
        return _report(args)
    except (JUnitParseError, StoreError) as exc:
        print(f"flakehunter: error: {exc}", file=sys.stderr)
        return 1


def _ingest(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.run_id:
        parser.error("--run-id is required outside GitHub Actions")
    if not args.commit:
        parser.error("--commit is required outside GitHub Actions")
    created_at = args.created_at or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    # Windows shells don't expand globs, so do it here.
    paths = [p for pattern in args.reports for p in (sorted(glob.glob(pattern)) or [pattern])]
    results = [result for path in paths for result in parse_file(path)]
    run = Run(args.run_id, args.commit, created_at, args.branch)
    with Store(args.db) as store:
        count = store.add_run(run, results)
    print(f"recorded {count} results from {len(paths)} report(s) as run {run.run_id} "
          f"@ {run.commit[:12]}")
    return 0


def _report(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        verdicts = analyze(store.executions())
    if not args.all:
        verdicts = [v for v in verdicts if v.status not in (Status.STABLE, Status.SKIPPED)]
    render = {"text": report.as_text, "markdown": report.as_markdown,
              "json": report.as_json}[args.format]
    print(render(verdicts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
