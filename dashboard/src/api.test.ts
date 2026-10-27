import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, fetchHistory, fetchVerdicts } from './api';

function respond(status: number, body: unknown) {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return vi.fn().mockResolvedValue(new Response(text, { status }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchVerdicts', () => {
  it('requests the project verdicts, tolerating a trailing slash on the base URL', async () => {
    const fetch = respond(200, { project: 'web app', runs: 0, summary: {}, verdicts: [] });
    vi.stubGlobal('fetch', fetch);

    const data = await fetchVerdicts('https://api.example.com/', 'web app');

    expect(fetch.mock.calls[0][0]).toBe('https://api.example.com/projects/web%20app/verdicts');
    expect(data.project).toBe('web app');
  });

  it('asks for stable tests only when told to', async () => {
    const fetch = respond(200, { project: 'p', runs: 0, summary: {}, verdicts: [] });
    vi.stubGlobal('fetch', fetch);

    await fetchVerdicts('https://api.example.com', 'p', { all: true });

    expect(fetch.mock.calls[0][0]).toBe('https://api.example.com/projects/p/verdicts?all=true');
  });

  it('turns an error response into an ApiError carrying the server message', async () => {
    vi.stubGlobal('fetch', respond(400, { error: 'invalid project' }));

    const error = await fetchVerdicts('https://api.example.com', 'p').catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(400);
    expect(error.message).toBe('invalid project');
  });

  it('falls back to the status code when the error body is not JSON', async () => {
    vi.stubGlobal('fetch', respond(502, '<html>Bad Gateway</html>'));

    const error = await fetchVerdicts('https://api.example.com', 'p').catch((e) => e);

    expect(error.message).toBe('HTTP 502');
  });

  it('reports an unreachable API as status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    const error = await fetchVerdicts('https://api.example.com', 'p').catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.message).toMatch(/could not reach/i);
  });
});

describe('fetchHistory', () => {
  it('encodes test ids with characters that mean something in URLs', async () => {
    const fetch = respond(200, { project: 'p', test_id: 'x', verdict: null, executions: [] });
    vi.stubGlobal('fetch', fetch);

    await fetchHistory('https://api.example.com', 'p', 'tests/a.py::test_x[a|b] #1&2');

    expect(fetch.mock.calls[0][0]).toBe(
      'https://api.example.com/projects/p/history?test_id=' +
        'tests%2Fa.py%3A%3Atest_x%5Ba%7Cb%5D%20%231%262',
    );
  });
});
