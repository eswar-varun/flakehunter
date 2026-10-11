"""Render verdicts as a terminal table, GitHub-flavoured Markdown, or JSON."""

from __future__ import annotations

import json
from collections import Counter

from .analysis import Status, Verdict

_HEADERS = ("status", "score", "fails/runs", "flaky commits", "test")


def _cells(v: Verdict) -> tuple[str, ...]:
    return (v.status.value, f"{v.score:.2f}", f"{v.failures}/{v.executions}",
            f"{v.flaky_commits}/{v.commits}", v.test_id)


def summary(verdicts: list[Verdict]) -> str:
    counts = Counter(v.status for v in verdicts)
    return ", ".join(f"{counts[s]} {s.value}" for s in Status if counts[s])


def as_text(verdicts: list[Verdict]) -> str:
    if not verdicts:
        return "No tests to report."
    rows = [_HEADERS, *(_cells(v) for v in verdicts)]
    widths = [max(len(row[i]) for row in rows) for i in range(len(_HEADERS) - 1)]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=False))
             + "  " + row[-1] for row in rows]
    return "\n".join([*lines, "", summary(verdicts)])


def as_markdown(verdicts: list[Verdict]) -> str:
    """Suitable for $GITHUB_STEP_SUMMARY or a PR comment."""
    if not verdicts:
        return "### FlakeHunter\n\nNo tests to report.\n"
    lines = ["### FlakeHunter", "", f"**{summary(verdicts)}**", "",
             "| " + " | ".join(_HEADERS) + " |", "|" + "---|" * len(_HEADERS)]
    for v in verdicts:
        status, score, fails, flaky, test_id = _cells(v)
        lines.append(f"| {status} | {score} | {fails} | {flaky} | `{_md_escape(test_id)}` |")
    return "\n".join(lines) + "\n"


def as_json(verdicts: list[Verdict]) -> str:
    return json.dumps([{
        "test_id": v.test_id,
        "status": v.status.value,
        "score": round(v.score, 4),
        "failure_rate": round(v.failure_rate, 4),
        "executions": v.executions,
        "failures": v.failures,
        "commits": v.commits,
        "flaky_commits": v.flaky_commits,
        "last_failure": v.last_failure,
    } for v in verdicts], indent=2)


def _md_escape(text: str) -> str:
    # Test ids can contain '|' (parametrize ids), which would split the table cell.
    return text.replace("|", "\\|").replace("`", "'")
