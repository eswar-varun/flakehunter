import type { HistoryResponse, VerdictsResponse } from './types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface RequestOptions {
  signal?: AbortSignal;
}

export function fetchVerdicts(
  baseUrl: string,
  project: string,
  { all = false, signal }: RequestOptions & { all?: boolean } = {},
): Promise<VerdictsResponse> {
  const query = all ? '?all=true' : '';
  return getJson(`${projectUrl(baseUrl, project)}/verdicts${query}`, signal);
}

export function fetchHistory(
  baseUrl: string,
  project: string,
  testId: string,
  { signal }: RequestOptions = {},
): Promise<HistoryResponse> {
  // Test ids are full of URL syntax (`/`, `::`, `[a|b]`, `#`), so they go in an encoded
  // query parameter rather than the path.
  return getJson(
    `${projectUrl(baseUrl, project)}/history?test_id=${encodeURIComponent(testId)}`,
    signal,
  );
}

function projectUrl(baseUrl: string, project: string): string {
  return `${baseUrl.replace(/\/+$/, '')}/projects/${encodeURIComponent(project)}`;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal, headers: { accept: 'application/json' } });
  } catch (error) {
    // A cancelled request is the caller's decision, not a failure to report.
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'Could not reach the API.');
  }
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === 'object' && 'error' in body && typeof body.error === 'string') {
        message = body.error;
      }
    } catch {
      // Not JSON (a gateway's HTML error page, say): the status code is all there is.
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}
