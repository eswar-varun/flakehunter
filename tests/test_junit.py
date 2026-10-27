from __future__ import annotations

import pytest

from flakehunter.junit import MAX_MESSAGE_CHARS, JUnitParseError, parse_file, parse_string
from flakehunter.model import Outcome


def _by_id(results):
    return {(r.test_id, r.attempt): r for r in results}


def test_parses_real_pytest_junit_output(pytester):
    pytester.makepyfile(test_sample="""
        import pytest

        def test_ok():
            pass

        def test_fails():
            assert 1 == 2

        @pytest.mark.skip(reason="not today")
        def test_skip():
            pass

        @pytest.fixture
        def boom():
            raise RuntimeError("setup exploded")

        def test_errors(boom):
            pass

        @pytest.mark.parametrize("x", [1, 2])
        def test_param(x):
            pass
    """)
    pytester.runpytest("--junitxml=report.xml")

    results = _by_id(parse_file(pytester.path / "report.xml"))

    assert results[("test_sample::test_ok", 0)].outcome is Outcome.PASSED
    assert results[("test_sample::test_fails", 0)].outcome is Outcome.FAILED
    assert "assert 1 == 2" in results[("test_sample::test_fails", 0)].message
    assert results[("test_sample::test_skip", 0)].outcome is Outcome.SKIPPED
    assert results[("test_sample::test_errors", 0)].outcome is Outcome.ERROR
    assert "setup exploded" in results[("test_sample::test_errors", 0)].message
    assert ("test_sample::test_param[1]", 0) in results
    assert ("test_sample::test_param[2]", 0) in results


SUREFIRE_WITH_RETRIES = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.example.CartTest" tests="3">
  <testcase name="addsItem" classname="com.example.CartTest" time="0.12">
    <flakyFailure message="expected: &lt;2&gt; but was: &lt;1&gt;" type="AssertionFailedError">trace</flakyFailure>
    <flakyFailure message="expected: &lt;2&gt; but was: &lt;1&gt;" type="AssertionFailedError">trace</flakyFailure>
  </testcase>
  <testcase name="removesItem" classname="com.example.CartTest" time="0.30">
    <failure message="timed out" type="TimeoutException">trace</failure>
    <rerunFailure message="timed out again" type="TimeoutException">trace</rerunFailure>
  </testcase>
  <testcase name="emptyCart" classname="com.example.CartTest" time="0.01"/>
</testsuite>"""


def test_surefire_flaky_retries_become_failed_attempts_before_the_pass():
    results = _by_id(parse_string(SUREFIRE_WITH_RETRIES))

    test_id = "com.example.CartTest::addsItem"
    assert [results[(test_id, i)].outcome for i in range(3)] == [
        Outcome.FAILED, Outcome.FAILED, Outcome.PASSED]
    assert results[(test_id, 0)].message == "expected: <2> but was: <1>"
    assert results[(test_id, 2)].duration_s == pytest.approx(0.12)
    assert results[(test_id, 0)].duration_s == 0.0


def test_surefire_reruns_follow_the_first_failure():
    results = _by_id(parse_string(SUREFIRE_WITH_RETRIES))

    test_id = "com.example.CartTest::removesItem"
    assert results[(test_id, 0)].message == "timed out"
    assert results[(test_id, 1)].message == "timed out again"
    assert all(results[(test_id, i)].outcome is Outcome.FAILED for i in range(2))


JEST_JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="jest tests" tests="2" failures="1">
  <testsuite name="cart" tests="2">
    <testcase classname="cart adds an item" name="cart adds an item" time="0.004"/>
    <testcase classname="cart totals the price" name="cart totals the price" time="0.002">
      <failure>
        Error: expect(received).toBe(expected)
        Expected: 30
      </failure>
    </testcase>
  </testsuite>
</testsuites>"""


def test_jest_junit_ids_are_not_doubled_and_message_comes_from_text():
    results = _by_id(parse_string(JEST_JUNIT))

    assert results[("cart adds an item", 0)].outcome is Outcome.PASSED
    failed = results[("cart totals the price", 0)]
    assert failed.outcome is Outcome.FAILED
    assert failed.message == "Error: expect(received).toBe(expected)"


def test_nested_suites_are_walked():
    xml = """<testsuites><testsuite name="outer"><testsuite name="inner">
             <testcase classname="a.B" name="c"/></testsuite></testsuite></testsuites>"""
    assert [r.test_id for r in parse_string(xml)] == ["a.B::c"]


def test_long_messages_are_truncated():
    xml = f'<testsuite><testcase name="t"><failure message="{"x" * 5000}"/></testcase></testsuite>'
    assert len(parse_string(xml)[0].message) == MAX_MESSAGE_CHARS


@pytest.mark.parametrize("xml", [
    # "billion laughs": entity expansion that would exhaust memory
    """<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>
       <testsuite><testcase name="&b;"/></testsuite>""",
    # XXE: an external entity that would read a local file into the report
    """<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>
       <testsuite><testcase name="&x;"/></testsuite>""",
], ids=["entity-expansion", "external-entity"])
def test_hostile_xml_is_rejected(xml):
    with pytest.raises(JUnitParseError):
        parse_string(xml)


@pytest.mark.parametrize("xml", [
    "<html><body>not a report</body></html>",
    "<testsuite><testcase classname='x'/></testsuite>",
    "<testsuite><testcase",
], ids=["wrong-root", "unnamed-testcase", "truncated"])
def test_invalid_reports_are_rejected(xml):
    with pytest.raises(JUnitParseError):
        parse_string(xml)


def test_parse_file_error_names_the_file(tmp_path):
    path = tmp_path / "broken.xml"
    path.write_text("<testsuite>", encoding="utf-8")
    with pytest.raises(JUnitParseError, match="broken.xml"):
        parse_file(path)


@pytest.mark.parametrize("time", ["inf", "nan", "-3", "abc", ""])
def test_unusable_durations_become_zero(time):
    [result] = parse_string(f'<testsuite><testcase name="t" time="{time}"/></testsuite>')

    assert result.duration_s == 0.0
