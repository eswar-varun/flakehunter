import type { Execution, HistoryResponse, Verdict, VerdictsResponse } from '../types';

export function verdict(overrides: Partial<Verdict> = {}): Verdict {
  return {
    test_id: 'tests/test_cart.py::test_total',
    status: 'flaky',
    score: 0.21,
    failure_rate: 0.25,
    executions: 8,
    failures: 2,
    commits: 3,
    flaky_commits: 1,
    last_failure: 'AssertionError: 41 != 42',
    ...overrides,
  };
}

export function verdictsResponse(verdicts: Verdict[], runs = 2): VerdictsResponse {
  const summary = { broken: 0, flaky: 0, suspect: 0, stable: 0, skipped: 0 };
  for (const v of verdicts) summary[v.status] += 1;
  return { project: 'shop', runs, summary, verdicts };
}

export function execution(overrides: Partial<Execution> = {}): Execution {
  return {
    run_id: 'run-1',
    commit: '4d6cdd6f0e8b2a1c',
    created_at: '2026-01-01T00:00:00+00:00',
    attempt: 0,
    outcome: 'passed',
    duration_s: 0.1,
    message: null,
    ...overrides,
  };
}

export function historyResponse(testId: string, executions: Execution[]): HistoryResponse {
  return { project: 'shop', test_id: testId, verdict: verdict({ test_id: testId }), executions };
}
