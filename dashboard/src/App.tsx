import { useEffect, useState, type FormEvent } from 'react';
import { HistoryPanel } from './HistoryPanel';
import { VerdictTable } from './VerdictTable';
import type { HistoryResponse, VerdictsResponse } from './types';

/** The two API calls, bound to a base URL; tests pass fakes. */
export interface Api {
  fetchVerdicts(
    project: string,
    options: { all: boolean; signal?: AbortSignal },
  ): Promise<VerdictsResponse>;
  fetchHistory(
    project: string,
    testId: string,
    options: { signal?: AbortSignal },
  ): Promise<HistoryResponse>;
}

interface Props {
  api: Api;
  initialProject?: string;
  onProjectChange?: (project: string) => void;
}

type Load =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'ready'; data: VerdictsResponse };

export function App({ api, initialProject = '', onProjectChange }: Props) {
  const [draft, setDraft] = useState(initialProject);
  const [project, setProject] = useState(initialProject);
  const [all, setAll] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [load, setLoad] = useState<Load>(initialProject ? { phase: 'loading' } : { phase: 'idle' });
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    if (!project) return;
    // A response for a project (or setting) that's no longer shown must not overwrite the
    // current one: abort the request and ignore it if it still arrives.
    let current = true;
    const controller = new AbortController();
    setLoad({ phase: 'loading' });
    api.fetchVerdicts(project, { all, signal: controller.signal }).then(
      (data) => current && setLoad({ phase: 'ready', data }),
      (error: Error) => {
        if (current && error.name !== 'AbortError') {
          setLoad({ phase: 'error', message: error.message });
        }
      },
    );
    return () => {
      current = false;
      controller.abort();
    };
  }, [api, project, all, attempt]);

  useEffect(() => {
    if (!project || !selected) return;
    let current = true;
    const controller = new AbortController();
    setHistory(null);
    setHistoryError(null);
    api.fetchHistory(project, selected, { signal: controller.signal }).then(
      (data) => current && setHistory(data),
      (error: Error) => current && error.name !== 'AbortError' && setHistoryError(error.message),
    );
    return () => {
      current = false;
      controller.abort();
    };
  }, [api, project, selected]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = draft.trim();
    if (!next) return;
    setSelected(null);
    setProject(next);
    onProjectChange?.(next);
  }

  return (
    <div className="app">
      <header className="masthead">
        <h1>FlakeHunter</h1>
        <form onSubmit={submit}>
          <label htmlFor="project">Project</label>
          <input
            id="project"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. my-service"
            autoComplete="off"
          />
          <button type="submit">Load</button>
        </form>
      </header>

      <main>
        {load.phase === 'idle' && <p className="empty">Enter a project to see its flaky tests.</p>}
        {load.phase === 'loading' && <p role="status">Loading verdicts…</p>}
        {load.phase === 'error' && (
          <div role="alert" className="error">
            <p>{load.message}</p>
            <button type="button" onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </button>
          </div>
        )}
        {load.phase === 'ready' && (
          <>
            <div className="summary">
              <p>
                {load.data.runs} runs · {load.data.summary.broken} broken ·{' '}
                {load.data.summary.flaky} flaky · {load.data.summary.suspect} suspect
              </p>
              <label>
                <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
                Show stable tests
              </label>
            </div>
            <div className="layout">
              <VerdictTable
                verdicts={load.data.verdicts}
                onSelect={setSelected}
                selected={selected ?? undefined}
              />
              {selected && (
                <HistoryPanel
                  testId={selected}
                  history={history}
                  error={historyError}
                  onClose={() => setSelected(null)}
                />
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
