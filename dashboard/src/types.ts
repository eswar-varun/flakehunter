// Response shapes of the FlakeHunter API (src/flakehunter/api.py).

export type Status = 'broken' | 'flaky' | 'suspect' | 'stable' | 'skipped';
export type Outcome = 'passed' | 'failed' | 'error' | 'skipped';

export interface Verdict {
  test_id: string;
  status: Status;
  /** Wilson lower bound of the failure rate: the ranking within a status. */
  score: number;
  failure_rate: number;
  executions: number;
  failures: number;
  commits: number;
  flaky_commits: number;
  last_failure: string | null;
}

export interface VerdictsResponse {
  project: string;
  runs: number;
  summary: Record<Status, number>;
  /** Most urgent first: broken, flaky, suspect, then by score. */
  verdicts: Verdict[];
}

export interface Execution {
  run_id: string;
  commit: string;
  created_at: string;
  attempt: number;
  outcome: Outcome;
  duration_s: number;
  message: string | null;
}

export interface HistoryResponse {
  project: string;
  test_id: string;
  verdict: Verdict | null;
  /** Oldest first. */
  executions: Execution[];
}
