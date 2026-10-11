"""Measure FlakeHunter's detection on the zoo, whose ground truth is in the test names.

Runs the zoo repeatedly (shuffled order, fresh randomness each time), ingests every report,
and after each run scores the verdicts against the labels:

    precision  of the tests reported flaky, how many really are
    recall     of the tests that really are flaky, how many were reported

The flaky tests are random, so one experiment is one sample. `--trials` repeats the whole
experiment from an empty history and reports the mean, which is the number worth quoting.

    python bench/evaluate_zoo.py --runs 20 --runs-per-commit 2 --trials 5

`--runs-per-commit 1` simulates CI where every run is a new commit (no same-commit
evidence); 2+ simulates re-runs or retries on the same commit.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean

from flakehunter.analysis import Status, Verdict, analyze
from flakehunter.junit import parse_file
from flakehunter.model import Run
from flakehunter.store import Store

ROOT = Path(__file__).resolve().parent.parent
_LABEL = re.compile(r"::test_(stable|flaky|broken|skipped)_")


def label(test_id: str) -> str:
    match = _LABEL.search(test_id)
    if not match:
        raise ValueError(f"zoo test without a label prefix: {test_id}")
    return match.group(1)


def run_zoo(report: Path, seed: int) -> None:
    subprocess.run(
        [sys.executable, "-m", "pytest", "zoo", "-q", "-p", "no:cacheprovider",
         f"--junitxml={report}"],
        cwd=ROOT, env={**os.environ, "ZOO_SHUFFLE_SEED": str(seed)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


def score(verdicts: list[Verdict], predicted: set[Status]) -> dict[str, float]:
    truth = {v.test_id for v in verdicts if label(v.test_id) == "flaky"}
    flagged = {v.test_id for v in verdicts if v.status in predicted}
    hits = len(truth & flagged)
    return {
        "precision": hits / len(flagged) if flagged else 1.0,
        "recall": hits / len(truth) if truth else 1.0,
        "broken_flagged": sum(1 for v in verdicts
                              if label(v.test_id) == "broken" and v.status in predicted),
    }


def experiment(runs: int, runs_per_commit: int, checkpoints: set[int], seed_base: int):
    """One experiment from an empty history. Returns (checkpoint -> scores, first detections)."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    at_checkpoint: dict[int, dict[str, dict[str, float]]] = {}
    first_detection: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / "history.db") as store:
        for i in range(1, runs + 1):
            report = Path(tmp) / f"run-{i}.xml"
            run_zoo(report, seed=seed_base + i)
            commit = f"commit-{(i - 1) // runs_per_commit:03d}"
            store.add_run(Run(f"run-{i}", commit, start + timedelta(minutes=i)),
                          parse_file(report))
            verdicts = analyze(store.executions())
            for v in verdicts:
                if v.status is Status.FLAKY and label(v.test_id) == "flaky":
                    first_detection.setdefault(v.test_id.split("::")[-1], i)
            if i in checkpoints:
                at_checkpoint[i] = {
                    "flaky": score(verdicts, {Status.FLAKY}),
                    "flaky+suspect": score(verdicts, {Status.FLAKY, Status.SUSPECT}),
                }
    return at_checkpoint, first_detection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--runs-per-commit", type=int, default=2)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--checkpoints", default="1,2,4,6,10,20,30")
    args = parser.parse_args()
    checkpoints = {c for c in map(int, args.checkpoints.split(",")) if c <= args.runs}
    checkpoints.add(args.runs)

    per_checkpoint: dict[int, list[dict]] = defaultdict(list)
    detections: dict[str, list[int | None]] = defaultdict(list)
    for trial in range(args.trials):
        scores, first = experiment(args.runs, args.runs_per_commit, checkpoints, trial * 10_000)
        for i, s in scores.items():
            per_checkpoint[i].append(s)
        for name in _flaky_test_names():
            detections[name].append(first.get(name))
        print(f"trial {trial + 1}/{args.trials} done", file=sys.stderr)

    def avg(i: int, mode: str, metric: str) -> float:
        return mean(s[mode][metric] for s in per_checkpoint[i])

    print(f"# Zoo evaluation\n\n{args.runs} runs, {args.runs_per_commit} run(s) per commit, "
          f"mean of {args.trials} trial(s).\n")
    print("| runs | precision | recall | broken mislabelled as flaky "
          "| recall incl. suspect | precision incl. suspect |")
    print("|---|---|---|---|---|---|")
    for i in sorted(per_checkpoint):
        print(f"| {i} | {avg(i, 'flaky', 'precision'):.0%} | {avg(i, 'flaky', 'recall'):.0%} "
              f"| {avg(i, 'flaky', 'broken_flagged'):.1f} "
              f"| {avg(i, 'flaky+suspect', 'recall'):.0%} "
              f"| {avg(i, 'flaky+suspect', 'precision'):.0%} |")

    print("\n## Runs until each flaky test was first confirmed (mean over trials)\n")
    for name, found in sorted(detections.items()):
        hits = [f for f in found if f is not None]
        when = f"{mean(hits):.1f}" if hits else "never"
        print(f"- `{name}`: {when} (detected in {len(hits)}/{len(found)} trials)")


def _flaky_test_names() -> list[str]:
    source = (ROOT / "zoo" / "test_zoo.py").read_text(encoding="utf-8")
    return re.findall(r"^def (test_flaky_\w+)", source, flags=re.MULTILINE)


if __name__ == "__main__":
    main()
