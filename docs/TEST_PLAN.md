# Test plan

## Scope

Milestone 1: JUnit parsing, history storage, classification and ranking, CLI, and the
evaluation harness. Out of scope until later milestones: ordering bisection, quarantine,
the AWS backend and the dashboard.

## Risks, highest first

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | A broken test is labelled flaky | a real regression is ignored and ships | broken-before-suspect rule (D3); zoo measures "broken mislabelled as flaky" every CI run; unit tests on the boundary cases |
| R2 | A stable test is labelled flaky (false positive) | people stop trusting the tool | same-commit evidence only for "flaky" (D2); precision tracked on the zoo |
| R3 | A runner's XML variant is misparsed | wrong outcomes recorded silently | tests against real pytest output plus Surefire and jest-junit samples |
| R4 | Hostile report crashes or exhausts the parser | outage or data exposure | defusedxml; entity-expansion and XXE tests |
| R5 | Re-uploads or sharding corrupt history | double counts or a manufactured flake | idempotency and run/commit-consistency tests |
| R6 | Mis-ranking | effort goes to the wrong tests first | Wilson-bound tests with known values and the motivating case |

## Test levels

| Level | Where | What it proves |
|---|---|---|
| Unit | `tests/test_stats.py`, `tests/test_analysis.py` | each classification rule and boundary; ranking maths |
| Format/contract | `tests/test_junit.py` | every supported XML variant maps to the right attempts and outcomes |
| Integration | `tests/test_store.py` | real SQLite: ordering, idempotency, transactions, persistence |
| End-to-end | `tests/test_cli.py` | ingest → report through the CLI, env defaults, exit codes |
| System / quality | `bench/evaluate_zoo.py` (also in CI) | detection precision and recall against ground truth |

## Test cases

### Parsing (`test_junit.py`)

| Case | Expected |
|---|---|
| Real pytest output: pass, assertion failure, skip, fixture error, parametrised | PASSED / FAILED with message / SKIPPED / ERROR / one id per parameter |
| Surefire `flakyFailure` ×2 then pass | attempts 0–1 FAILED, attempt 2 PASSED, duration on attempt 2 |
| Surefire `failure` + `rerunFailure` | attempt 0 = original failure, attempt 1 = rerun, both FAILED |
| jest-junit (classname == name) | id not doubled; message from first non-blank text line |
| Nested suites | all testcases found |
| Message over 500 chars | truncated to 500 |
| Entity expansion / external entity | rejected with `JUnitParseError` |
| Wrong root / unnamed testcase / truncated file | rejected; file name in error |

### Storage (`test_store.py`)

| Case | Expected |
|---|---|
| Runs inserted out of time order | read back grouped by test, in time order |
| Same report ingested twice | no duplicates |
| Two shards, one run id | union of both |
| Retry attempts | kept as separate rows |
| Run id reused for another commit | refused, and nothing written |
| Naive timestamp | refused |
| Reopen the file | data intact |

### Classification (`test_analysis.py`)

| History | Expected |
|---|---|
| pass + fail, same commit | flaky |
| fail then pass as retries in one run | flaky |
| pass + error, same commit | flaky (errors are failures) |
| fails every attempt on latest commit | broken |
| failed on old commit, passes on new | stable (fixed regression) |
| fail/pass/fail/pass across four commits | suspect |
| intermittent history, latest commit failing | **broken** (R1) |
| only skips | skipped; skips never counted as runs |
| 1/2 vs 30/100 failures | 30/100 ranked first |
| mixed statuses | order broken → flaky → suspect → stable |
| ungrouped input | `ValueError` |

### CLI (`test_cli.py`)

Ingest + report end to end (JSON), `--all`, Markdown table with an escaped `|`, GitHub
Actions env defaults (`run_id = RUN_ID-ATTEMPT`), missing commit outside CI (exit 2),
glob over shards, unparseable report (exit 1 with message).

## Entry and exit criteria

- **Entry:** code builds, `ruff check` clean.
- **Exit (per merge):** all tests pass in CI; zoo evaluation reports zero broken tests
  mislabelled as flaky.
