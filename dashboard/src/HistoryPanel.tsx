import type { HistoryResponse } from './types';
import { percent, shortSha } from './verdicts';

interface Props {
  testId: string;
  history: HistoryResponse | null;
  error: string | null;
  onClose: () => void;
}

const time = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export function HistoryPanel({ testId, history, error, onClose }: Props) {
  const verdict = history?.verdict;
  return (
    <section className="history" role="region" aria-label={`History of ${testId}`}>
      <header>
        <h2>{testId}</h2>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </header>

      {error && <p role="alert">{error}</p>}
      {!history && !error && <p role="status">Loading history…</p>}

      {verdict && (
        <p className="verdict">
          <span className={`badge ${verdict.status}`}>{verdict.status}</span> failed{' '}
          {verdict.failures} of {verdict.executions} attempts ({percent(verdict.failure_rate)})
          across {verdict.commits} commits; passed and failed on the same commit{' '}
          {verdict.flaky_commits} times.
        </p>
      )}

      {history && (
        <ol className="executions">
          {history.executions.map((e) => (
            <li key={`${e.run_id}-${e.attempt}`} className={e.outcome}>
              <span className={`outcome ${e.outcome}`}>{e.outcome}</span>
              <code>{shortSha(e.commit)}</code>
              <span>{e.run_id}</span>
              {e.attempt > 0 && <span className="retry">retry {e.attempt}</span>}
              <time dateTime={e.created_at}>{time.format(new Date(e.created_at))}</time>
              {e.message && <p className="message">{e.message}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
