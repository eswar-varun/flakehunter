import { useState } from 'react';
import type { Status, Verdict } from './types';
import { STATUSES, countByStatus, filterVerdicts, percent, type Filter } from './verdicts';

const LABELS: Record<Status, string> = {
  broken: 'Broken',
  flaky: 'Flaky',
  suspect: 'Suspect',
  stable: 'Stable',
  skipped: 'Skipped',
};

interface Props {
  verdicts: Verdict[];
  onSelect: (testId: string) => void;
  selected?: string;
}

export function VerdictTable({ verdicts, onSelect, selected }: Props) {
  const [filter, setFilter] = useState<Filter>({ status: 'all', query: '' });

  if (verdicts.length === 0) {
    return <p className="empty">No broken, flaky or suspect tests.</p>;
  }

  const counts = countByStatus(verdicts);
  const shown = filterVerdicts(verdicts, filter);
  const choices: { value: Filter['status']; label: string; count: number }[] = [
    { value: 'all', label: 'All', count: verdicts.length },
    ...STATUSES.filter((s) => counts[s] > 0).map((s) => ({
      value: s,
      label: LABELS[s],
      count: counts[s],
    })),
  ];

  return (
    <div className="verdicts">
      <div className="toolbar">
        <div className="chips" role="group" aria-label="Filter by status">
          {choices.map((c) => (
            <button
              key={c.value}
              type="button"
              className={`chip ${c.value}`}
              aria-pressed={filter.status === c.value}
              onClick={() => setFilter({ ...filter, status: c.value })}
            >
              {c.label} <span className="count">{c.count}</span>
            </button>
          ))}
        </div>
        <input
          type="search"
          aria-label="Filter by test name"
          placeholder="Filter by test name"
          value={filter.query}
          onChange={(e) => setFilter({ ...filter, query: e.target.value })}
        />
      </div>

      {shown.length === 0 ? (
        <p className="empty">No tests match this filter.</p>
      ) : (
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col" title="Wilson lower bound of the failure rate">
                  Score
                </th>
                <th scope="col">Failure rate</th>
                <th scope="col">Fails / runs</th>
                <th scope="col">Flaky commits</th>
                <th scope="col">Test</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((v) => (
                <tr key={v.test_id} aria-selected={v.test_id === selected}>
                  <td>
                    <span className={`badge ${v.status}`}>{v.status}</span>
                  </td>
                  <td className="num">{v.score.toFixed(2)}</td>
                  <td className="num">{percent(v.failure_rate)}</td>
                  <td className="num">{`${v.failures} / ${v.executions}`}</td>
                  <td className="num">{`${v.flaky_commits} / ${v.commits}`}</td>
                  <td className="test">
                    <button type="button" className="link" onClick={() => onSelect(v.test_id)}>
                      {v.test_id}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
