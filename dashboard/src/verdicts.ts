import type { Status, Verdict } from './types';

/** Report order: what needs a human first. */
export const STATUSES: readonly Status[] = ['broken', 'flaky', 'suspect', 'stable', 'skipped'];

export interface Filter {
  status: Status | 'all';
  query: string;
}

/** Verdicts matching the filter, keeping the API's ranking. */
export function filterVerdicts(verdicts: Verdict[], { status, query }: Filter): Verdict[] {
  const needle = query.trim().toLowerCase();
  return verdicts.filter(
    (v) =>
      (status === 'all' || v.status === status) &&
      (!needle || v.test_id.toLowerCase().includes(needle)),
  );
}

export function countByStatus(verdicts: Verdict[]): Record<Status, number> {
  const counts = Object.fromEntries(STATUSES.map((s) => [s, 0])) as Record<Status, number>;
  for (const v of verdicts) counts[v.status] += 1;
  return counts;
}

export function percent(rate: number): string {
  // A rare failure shouldn't read as "0%", which looks like no failures at all.
  if (rate > 0 && rate < 0.01) return '<1%';
  return `${Math.round(rate * 100)}%`;
}

export function shortSha(commit: string): string {
  return /^[0-9a-f]{8,}$/i.test(commit) ? commit.slice(0, 7) : commit;
}
