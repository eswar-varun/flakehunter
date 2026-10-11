# Interview prep: milestone 1

Written for an **SDE-T** loop: expect test-design questions, data-structure trade-offs,
and "how do you know your tool is right?" **Answer each one out loud before reading.**

## The 60-second pitch

> "Flaky tests teach teams to re-run builds until they're green, and that's how real bugs
> get through. I built FlakeHunter to find them from the JUnit XML every runner already
> produces. The core rule is simple and high-precision: if a test passed and failed on the
> *same commit*, the code didn't change, so it's flaky. Anything failing every time on the
> latest commit is reported as *broken*, never flaky, because mislabelling a real regression
> is the worst mistake this tool could make. Flaky tests are ranked by the Wilson lower bound
> of their failure rate, so one failure in two runs doesn't outrank 30 in 100. To prove it
> works I built a zoo of tests with known ground truth: random, timing, async-ordering and
> order-dependent flakes plus broken tests. CI measures precision and recall on it every
> push."

## Core questions

**1. What is a flaky test, operationally?**
One whose outcome changes without the code changing. That's why same-commit evidence is
the definition (D2). Cross-commit flips are only *suspect*, because the change might be
the cause.

**2. Flaky vs. broken: how do you tell, and why does it matter?**
Broken = fails every attempt on the latest commit. It matters because the costly error is
calling a real regression "flaky": the team ignores it and it ships. So broken is checked
*before* suspect, even for tests with a flaky past (D3,
`test_an_intermittent_test_failing_on_the_latest_commit_is_treated_as_broken`).

**3. Why not just auto-retry failing tests?**
Retries hide the symptom, cost CI time, and also hide real intermittent bugs (races in
product code, not just the test). FlakeHunter *uses* retries as evidence and keeps the
history, so flakes get fixed instead of masked.

**4. Explain the Wilson score and why you didn't use the raw rate.**
Raw rate ignores sample size: 1/2 = 50% beats 30/100 = 30%. The Wilson interval's lower
bound is "the failure rate we're 95% confident is at least this". It behaves well at small
n, where the normal approximation breaks down (it can go negative). → `stats.py`, D4

**5. Where did you choose a hash table over an array, or vice versa?**
Per-commit pass/fail counts: dict, O(1) per update, and insertion order gives chronology
for free (sorting would be O(h log h) and lose it). The grouping check: a set of finished
ids, O(1) membership. The analysis itself streams a sorted sequence with `groupby`
instead of building a dict of all histories: O(h) memory instead of O(n). (D7)

**6. What's the complexity of `report`?**
The DB returns rows sorted (via index + sort): O(n log n) worst case, then one O(n) pass.
Memory is O(h) for the longest single history plus O(t) verdicts for t tests.

**7. How do you know FlakeHunter itself is correct?** *(the SDE-T question)*
Five levels (see TEST_PLAN.md): unit tests on every classification boundary; parsing
tested against XML produced by the *real* installed pytest (pytester), plus Surefire and
Jest samples; integration tests on real SQLite; CLI end-to-end; and the zoo, a suite with
ground truth in the test names, where CI measures precision, recall, and "broken
mislabelled as flaky" on every push.

**8. Why does the zoo average over trials?**
The flaky tests are random, so one experiment is one sample. Quoting a single run's number
would be cherry-picking. `--trials` repeats from empty history and reports the mean.

**9. What security issues does a test-report parser have?**
Reports are untrusted (any fork's PR can produce one). XML entity expansion can exhaust
memory; external entities (XXE) can read local files into the report. `defusedxml` rejects
both, and there are tests for both. Also data handling: failure messages can contain
secrets or personal data, so only 500 chars are kept. (D6)

**10. CI retries the upload step. What happens?**
Nothing bad: rows are keyed by (run_id, test_id, attempt) with insert-or-replace, so it's
idempotent, and shards of one run accumulate. A run id reused for a *different* commit is
refused, because it would fabricate same-commit evidence. (D5)

**11. How would you scale this to a company-wide CI (millions of results a day)?**
Same access pattern on DynamoDB: partition key test_id, sort key created_at#run#attempt,
batch writes on ingest. Keep incremental per-test aggregates (counts per commit) updated on
write, so reports don't rescan history. Partition hot tests (run thousands of times a day)
by date if one key gets too hot. (Milestone 4.)

**12. What would make FlakeHunter wrong?**
Renamed tests (history resets); ids containing random values (every run looks new);
quarantine misuse hiding new failures (milestone 2 design: quarantine by test id and
*known* failure signature only).

**13. Walk me through a test plan for this.**
Start from risks, highest impact first (R1: broken labelled flaky), then map each risk to
a level and to concrete cases. → TEST_PLAN.md

## Likely follow-ups

- *Your zoo flakes are synthetic. Does that matter?* Yes: real flakes have messier rates
  and correlated failures. Milestone 5 runs FlakeHunter on a real open-source project's CI
  history.
- *How would you find the polluting test for an order-dependent flake?* Delta debugging
  (ddmin) over the tests that ran before it: O(log n) reruns for a single polluter versus
  O(n) one at a time. (Milestone 2.)
- *Array or hash table for the quarantine list lookup during a test run?* Set: O(1) per
  test, and a test run checks every test.

## Amazon leadership-principle angles

- **Customer Obsession / Insist on the Highest Standards:** broken-before-suspect, so a
  regression never gets waved through.
- **Dive Deep:** measuring detection on ground truth instead of eyeballing output.
- **Ownership:** idempotent, shard-safe ingestion, built for how CI actually behaves
  (retries, sharding, re-runs).
- **Are Right, A Lot:** precision-first labels; suspect is kept separate from flaky.

## Exercises

1. In `analysis.py`, move the `SUSPECT` check above `BROKEN`. Which tests fail? Describe
   the production incident this would cause.
2. Replace the Wilson score with the raw failure rate. Which test fails, and why is its
   expectation right?
3. Remove the commit check in `Store.add_run`, then write a two-line scenario that makes a
   stable test look flaky.
4. Run `python bench/evaluate_zoo.py --runs 20 --runs-per-commit 1 --trials 3`. Why does
   recall for "flaky" collapse, and what does "incl. suspect" recover?
