# Design FAQ

Why FlakeHunter decides the way it does. Each answer points to the decision in
[DESIGN.md](DESIGN.md) or the case in [TEST_PLAN.md](TEST_PLAN.md) that covers it.

## Classification

**What counts as a flaky test?**
One whose outcome changes without the code changing. That's why passing and failing on the
*same commit*, including retries within one run, is the definition of **flaky** (D2). Flips
across commits are only **suspect**, because the change in between might be the cause.

**How is "flaky" told apart from "broken", and why does the order matter?**
A test that fails every attempt on the latest commit it ran on is **broken**, and that check
runs *before* the suspect check, even for tests with an intermittent past (D3). The costly
mistake for this tool is calling a real regression "probably flaky": people ignore it and it
ships. Pinned by `test_an_intermittent_test_failing_on_the_latest_commit_is_treated_as_broken`.

**Why not just retry failing tests automatically?**
Retries hide the symptom, cost CI time, and also hide genuine intermittent bugs in product
code, such as race conditions. FlakeHunter *uses* retries as evidence and keeps the history,
so flakes get fixed rather than masked.

## Ranking

**Why the Wilson score instead of the raw failure rate?**
The raw rate ignores sample size: 1 failure in 2 runs (50%) would outrank 30 in 100 (30%),
though the second is far stronger evidence of a recurring problem. The lower bound of the 95%
Wilson interval answers "at least how often does this fail, given what we've seen?". It
behaves well at small sample sizes, where the normal approximation can go negative (D4,
`stats.py`).

## Data structures and complexity

**Where does it use a hash table, and where a sequence?**
- **Per-commit pass/fail counts:** a dict. One O(1) update per execution, and insertion
  order gives chronology for free; sorting would cost O(h log h) and lose it.
- **The grouping check:** a set of finished test ids, O(1) per group.
- **The analysis itself:** streams a sorted sequence with `groupby` rather than building
  a dict of every history: O(h) memory for the longest single history instead of O(n) for
  everything (D7).

**What's the cost of a report?**
The database returns rows sorted by test and time (index plus sort, O(n log n) at worst),
then one O(n) pass. Memory is O(h) plus one verdict per test.

## Correctness and safety

**How do you know the tool itself is right?**
Five levels (see the test plan):
1. Unit tests on every classification boundary.
2. Parser tests against XML produced by the real installed pytest, plus Maven Surefire and
   jest-junit samples.
3. Integration tests on real SQLite.
4. CLI end-to-end tests.
5. The zoo: a suite whose ground truth is in the test names. CI measures precision, recall,
   and "broken mislabelled as flaky" on every push.

**Why does the zoo evaluation average over trials?**
The flaky tests are random, so one experiment is one sample. `--trials` repeats the
experiment from an empty history and reports the mean.

**What can go wrong when parsing test reports?**
Reports are untrusted: any job, including one from a fork's pull request, can produce one.
XML entity expansion can exhaust memory, and external entities (XXE) can read local files
into the report. `defusedxml` rejects both, and both are tested. Failure messages can contain
secrets or personal data that a test printed, so only 500 characters are kept (D6).

**What if CI retries the upload step, or shards one run across machines?**
Rows are keyed by `(run_id, test_id, attempt)` and written with insert-or-replace, so a
repeated upload changes nothing and shards of one run accumulate. A run id reused for a
*different* commit is refused, because merging them would fabricate same-commit evidence (D5).

## Scaling and limits

**How would this scale to a company-wide CI?**
With the same access pattern on DynamoDB: partition key `test_id` and sort key
`created_at#run_id#attempt`, batch writes on ingest, and per-test aggregates updated on write
so reports don't rescan history. Very hot tests can be partitioned further by date
(milestone 4).

**What makes it wrong today?**
- Renamed tests lose their history.
- Test ids containing random values look new on every run.
- No source awareness: it can't tell whether a "suspect" test's own code changed.

## Break it yourself

1. In `analysis.py`, move the `SUSPECT` check above `BROKEN`. Which test fails, and what
   production incident would that allow?
2. Replace the Wilson score with the raw failure rate. Which test fails, and why is its
   expectation right?
3. Remove the commit check in `Store.add_run`, then write a two-line scenario that makes a
   stable test look flaky.
4. Run `python bench/evaluate_zoo.py --runs 20 --runs-per-commit 1 --trials 3`. Why does
   recall for "flaky" collapse, and what does "incl. suspect" recover?
