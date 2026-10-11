"""Parse JUnit XML: the one report format pytest, Maven Surefire, Gradle, Jest and most other
test runners can all emit, which is what lets FlakeHunter work with any language.

Reports are untrusted input (any CI job, any fork can upload one), so parsing goes through
defusedxml: a crafted file with nested entities ("billion laughs") is rejected instead of
exhausting memory.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

from .model import CaseResult, Outcome

MAX_MESSAGE_CHARS = 500

# Maven Surefire records retries inside the final <testcase> element:
#   <flakyFailure>/<flakyError>   an attempt that failed before a later attempt passed
#   <rerunFailure>/<rerunError>   an attempt that failed again after the first failure
_RETRY_TAGS = {
    "flakyFailure": Outcome.FAILED,
    "flakyError": Outcome.ERROR,
    "rerunFailure": Outcome.FAILED,
    "rerunError": Outcome.ERROR,
}


class JUnitParseError(ValueError):
    pass


def parse_file(path: str | Path) -> list[CaseResult]:
    try:
        root = SafeET.parse(path).getroot()
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise JUnitParseError(f"{path}: {exc}") from exc
    return _parse_root(root, str(path))


def parse_string(xml: str | bytes) -> list[CaseResult]:
    try:
        root = SafeET.fromstring(xml)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise JUnitParseError(str(exc)) from exc
    return _parse_root(root, "<string>")


def _parse_root(root: Element, source: str) -> list[CaseResult]:
    if root.tag not in ("testsuites", "testsuite"):
        raise JUnitParseError(f"{source}: not a JUnit report (root element <{root.tag}>)")
    results: list[CaseResult] = []
    # iter() walks nested <testsuite> elements too, which Gradle and some Jest setups emit.
    for case in root.iter("testcase"):
        results.extend(_parse_case(case, source))
    return results


def _parse_case(case: Element, source: str) -> list[CaseResult]:
    test_id = _test_id(case, source)
    outcome, message = _final_outcome(case)
    retries = [(_RETRY_TAGS[child.tag], _message(child)) for child in case
               if child.tag in _RETRY_TAGS]
    # Passed in the end: the recorded failures came first. Failed in the end: the first
    # failure is the <failure> element itself and the reruns followed it.
    attempts = [*retries, (outcome, message)] if outcome is Outcome.PASSED \
        else [(outcome, message), *retries]
    duration = _seconds(case.get("time"))
    last = len(attempts) - 1
    # Reports carry one time for the whole testcase; it's attributed to the final attempt.
    return [CaseResult(test_id, o, duration if i == last else 0.0, i, m)
            for i, (o, m) in enumerate(attempts)]


def _test_id(case: Element, source: str) -> str:
    classname = (case.get("classname") or "").strip()
    name = (case.get("name") or "").strip()
    if not name:
        raise JUnitParseError(f"{source}: <testcase> without a name")
    # jest-junit repeats the suite in both attributes by default; don't double it up.
    if not classname or classname == name or name.startswith(f"{classname} "):
        return name
    return f"{classname}::{name}"


def _final_outcome(case: Element) -> tuple[Outcome, str | None]:
    for tag, outcome in (("failure", Outcome.FAILED), ("error", Outcome.ERROR),
                         ("skipped", Outcome.SKIPPED)):
        element = case.find(tag)
        if element is not None:
            return outcome, _message(element)
    return Outcome.PASSED, None


def _message(element: Element) -> str | None:
    text = element.get("message") or next(
        (line.strip() for line in (element.text or "").splitlines() if line.strip()), None)
    return text[:MAX_MESSAGE_CHARS] if text else None


def _seconds(value: str | None) -> float:
    try:
        return max(0.0, float(value)) if value else 0.0
    except ValueError:
        return 0.0
