# FlakeHunter

[![CI](https://github.com/eswar-varun/flakehunter/actions/workflows/ci.yml/badge.svg)](https://github.com/eswar-varun/flakehunter/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Find, rank and triage flaky tests from the JUnit XML your CI already produces.

A flaky test passes and fails on the same code. Each one teaches a team to hit "re-run"
until the build goes green, and eventually a real bug gets re-run straight into
production. FlakeHunter records every CI run, separates **flaky** tests from genuinely
**broken** ones, and ranks them by how much evidence there is, so the worst offenders get
fixed first.

> **Status: milestones 1 and 4 of 5.** Detection and ranking work from the CLI, and from a
> serverless AWS backend with a React dashboard. See the [roadmap](#roadmap).

```mermaid
flowchart LR
    CI["CI run<br/>(pytest, Maven, Gradle, Jest…)"] -->|JUnit XML| I["flakehunter ingest"]
    I --> H[("run history<br/>SQLite")]
    H --> A["flakehunter report"]
    A --> O["broken / flaky / suspect<br/>table · Markdown · JSON"]
    CI -->|"POST JUnit XML"| API["API Gateway → Lambda"]
    API --> DB[("DynamoDB")]
    DASH["React dashboard"] -->|GET| API
```

## How it decides

| Status | Rule | Why |
|---|---|---|
| **broken** | failed every attempt on the latest commit it ran on | a real failure until proven otherwise |
| **flaky** | passed *and* failed on the same commit (including retries within one run) | the code didn't change, so the outcome came from timing, ordering, randomness or shared state |
| **suspect** | failed intermittently across commits, never on the same commit | weaker evidence: the code changed in between |
| **stable** | everything else, including regressions that were fixed | |

Within a status, tests are ranked by the **Wilson-score lower bound** of their failure rate,
so a test that failed once in two runs doesn't outrank one that failed 30 times in 100.
The reasoning behind every rule is in [docs/DESIGN.md](docs/DESIGN.md).

## Quickstart

```bash
pip install -e ".[dev]"

# after each CI run (any runner that writes JUnit XML)
pytest --junitxml=report.xml
flakehunter ingest report.xml --run-id "$CI_RUN_ID" --commit "$(git rev-parse HEAD)"

# whenever you want to triage
flakehunter report                    # broken, flaky and suspect tests
flakehunter report --all              # include stable ones
flakehunter report --format markdown  # for a PR comment or job summary
flakehunter report --format json
```

Sharded CI? Ingest every shard under the same `--run-id`, or pass a glob:
`flakehunter ingest "reports/*.xml"`. Re-uploading a report is harmless: ingestion is
idempotent.

### GitHub Actions

Inside Actions, `--run-id` and `--commit` default to the workflow's run id, attempt and
SHA. Each "Re-run jobs" attempt counts as a new run on the same commit, which is exactly
the evidence that confirms a flake.

```yaml
- run: pytest --junitxml=report.xml
- if: always()
  run: |
    flakehunter ingest report.xml
    flakehunter report --format markdown >> "$GITHUB_STEP_SUMMARY"
```

(Persist the history file between runs with `actions/cache` or an artifact, or upload to
the AWS backend below, which keeps the history for you.)

## Serverless backend and dashboard

API Gateway → one Lambda → one DynamoDB table, defined with the AWS CDK in
[`infra/`](infra/). The Lambda runs the same parser and analysis as the CLI. A React and
TypeScript dashboard in [`dashboard/`](dashboard/) reads from it. Design notes, including
the DynamoDB key design and how uploads stay idempotent without one big transaction, are in
[docs/DESIGN.md](docs/DESIGN.md#serverless-backend-milestone-4).

![The dashboard after 10 runs of the zoo: three broken tests, then five flaky ones ranked by Wilson score](docs/dashboard.png)

| Route | Auth | |
|---|---|---|
| `POST /projects/{project}/runs?run_id=&commit=` | bearer token | upload a JUnit XML report |
| `GET /projects/{project}/verdicts[?all=true]` | none | broken, flaky and suspect tests, ranked |
| `GET /projects/{project}/history?test_id=` | none | one test's executions and verdict |

### Try it locally (no AWS account)

```bash
pip install -e ".[dev]"
python dev/local_api.py --seed 10      # real handler + in-memory DynamoDB, 10 runs of the zoo
cd dashboard && npm ci && npm run dev  # open http://localhost:5173/?project=zoo
```

### Deploy to AWS

You need an AWS account with credentials configured (`aws configure`), Node.js and
Python 3.12.

```bash
pip install -e ".[infra]"
npx aws-cdk@2 bootstrap    # once per account and region
npx aws-cdk@2 deploy       # prints ApiUrl and UploadTokenSecretArn
aws secretsmanager get-secret-value --secret-id <UploadTokenSecretArn> \
    --query SecretString --output text   # the upload token
```

Add `-c allowedOrigins=https://your-dashboard.example.com` to restrict CORS to the
dashboard's origin. Then upload from CI:

```yaml
- if: always()
  run: |
    curl --fail-with-body -X POST "$FLAKEHUNTER_API/projects/my-service/runs?run_id=$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT&commit=$GITHUB_SHA" \
      -H "Authorization: Bearer $FLAKEHUNTER_TOKEN" -H "Content-Type: application/xml" \
      --data-binary @report.xml
  env:
    FLAKEHUNTER_API: ${{ vars.FLAKEHUNTER_API }}
    FLAKEHUNTER_TOKEN: ${{ secrets.FLAKEHUNTER_TOKEN }}
```

Build the dashboard against the deployed API with `VITE_API_URL=<ApiUrl> npm run build`,
and host `dashboard/dist/` on any static host.

**Cost:** nothing while idle except the Secrets Manager secret (about $0.40 a month).
Requests are on-demand, and the API is throttled to 10 requests a second. `npx aws-cdk@2
destroy` removes everything except the DynamoDB table, which is kept on purpose; delete it
from the console if you want it gone.

## Does it work? The zoo

[`zoo/test_zoo.py`](zoo/test_zoo.py) is a suite with known ground truth: stable tests,
broken tests, and flaky tests built from the root causes seen most often in real suites
(random failures at 3%, 10% and 30%, a timing assumption, an async ordering assumption, and
an order-dependent test whose state leaks from another test). Every test's name says what it
really is, so detection can be scored exactly:

```bash
python bench/evaluate_zoo.py --runs 20 --runs-per-commit 2 --trials 5
```

This reports precision (of the tests flagged flaky, how many are), recall (of the flaky
tests, how many were flagged), how often a broken test was mislabelled as flaky, and how
many runs each flaky test took to be confirmed. CI runs a short version on every push and
posts the table to the job summary.

### Results

23 zoo tests, 2 runs per commit, mean of 5 independent trials:

| Runs so far | Precision | Recall | Broken tests labelled flaky |
|---|---|---|---|
| 4 | 100% | 47% | 0 |
| 10 | 100% | 67% | 0 |
| 20 | 100% | 83% | 0 |

Average number of runs before each flaky test was confirmed:

| Flaky test | Root cause | Confirmed after | Caught in |
|---|---|---|---|
| `async_completion_order` | assumes task completion order | 2.0 runs | 5/5 trials |
| `order_victim` | state leaked by another test | 4.4 runs | 5/5 trials |
| `random_30pct` | fails 30% of the time | 6.4 runs | 5/5 trials |
| `timing_worker_timeout` | timeout races a slow worker | 6.4 runs | 5/5 trials |
| `random_10pct` | fails 10% of the time | 12.0 runs | 4/5 trials |
| `random_3pct` | fails 3% of the time | 18.0 runs | 1/5 trials |

Nothing is ever wrongly flagged, because a test is only called flaky on direct same-commit
evidence. The cost is recall on rare flakes: a test that fails 3% of the time usually needs
more than 20 runs of history to be caught.

## Tests

```bash
pytest                          # 94 tests (the 7 CDK template tests need .[infra])
ruff check .
cd dashboard && npm test        # 32 tests
```

The parser is tested against XML produced by the real installed pytest (via `pytester`),
Maven Surefire retry output, jest-junit output, nested Gradle-style suites, and hostile
input (entity expansion, XXE). See the [test plan](docs/TEST_PLAN.md).

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1. Detect & rank | JUnit ingest (pytest, Surefire, Jest), history store, broken/flaky/suspect classification, Wilson ranking, CLI, ground-truth zoo + evaluation | ✅ |
| 2. Root cause: ordering | pytest plugin to replay a given test order; **delta debugging** to find the test that pollutes an order-dependent one in O(log n) reruns; quarantine that doesn't hide new failures | ⏳ |
| 3. Root cause: signatures | cluster failures by normalised stack-trace signature; GitHub Action | ⏳ |
| 4. AWS + dashboard | serverless backend (API Gateway, Lambda, DynamoDB via CDK) and a React/TypeScript dashboard built test-first | ✅ |
| 5. Benchmarks & polish | measured results on the zoo and on a real open-source project's CI history | ⏳ |

## Docs

- [docs/DESIGN.md](docs/DESIGN.md): architecture, data model, decisions and trade-offs.
- [docs/TEST_PLAN.md](docs/TEST_PLAN.md): risks, test levels, and the case-by-case plan.
- [docs/FAQ.md](docs/FAQ.md): questions this design invites, and exercises for
  understanding it by breaking it.

## License

MIT
