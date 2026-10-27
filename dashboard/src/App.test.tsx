import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import { App, type Api } from './App';
import type { VerdictsResponse } from './types';
import { execution, historyResponse, verdict, verdictsResponse } from './test/fixtures';

const flaky = verdict({ test_id: 'tests/cart.py::test_discount', status: 'flaky' });

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    fetchVerdicts: vi.fn().mockResolvedValue(verdictsResponse([flaky], 4)),
    fetchHistory: vi.fn().mockResolvedValue(
      historyResponse(flaky.test_id, [
        execution({ run_id: 'run-1', outcome: 'failed', message: 'AssertionError: 41 != 42' }),
        execution({ run_id: 'run-2', outcome: 'passed' }),
      ]),
    ),
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe('App', () => {
  it('asks for a project when it has none', () => {
    render(<App api={fakeApi()} />);

    expect(screen.getByText('Enter a project to see its flaky tests.')).toBeInTheDocument();
  });

  it('loads the initial project and shows its verdicts', async () => {
    const api = fakeApi();
    render(<App api={api} initialProject="shop" />);

    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    expect(await screen.findByRole('button', { name: flaky.test_id })).toBeInTheDocument();
    expect(screen.getByText(/4 runs/)).toBeInTheDocument();
    expect(api.fetchVerdicts).toHaveBeenCalledWith('shop', expect.objectContaining({ all: false }));
  });

  it('loads the project typed into the form', async () => {
    const api = fakeApi();
    render(<App api={api} />);

    await userEvent.type(screen.getByLabelText('Project'), 'shop');
    await userEvent.click(screen.getByRole('button', { name: 'Load' }));

    expect(await screen.findByRole('button', { name: flaky.test_id })).toBeInTheDocument();
    expect(api.fetchVerdicts).toHaveBeenCalledWith('shop', expect.anything());
  });

  it('shows the error and retries on request', async () => {
    const fetchVerdicts = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(0, 'Could not reach the API.'))
      .mockResolvedValueOnce(verdictsResponse([flaky]));
    render(<App api={fakeApi({ fetchVerdicts })} initialProject="shop" />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not reach the API.');

    await userEvent.click(within(alert).getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('button', { name: flaky.test_id })).toBeInTheDocument();
    expect(fetchVerdicts).toHaveBeenCalledTimes(2);
  });

  it('includes stable tests when asked', async () => {
    const api = fakeApi();
    render(<App api={api} initialProject="shop" />);
    await screen.findByRole('button', { name: flaky.test_id });

    await userEvent.click(screen.getByLabelText('Show stable tests'));

    await waitFor(() =>
      expect(api.fetchVerdicts).toHaveBeenLastCalledWith(
        'shop',
        expect.objectContaining({ all: true }),
      ),
    );
  });

  it("opens a test's history, oldest first, and closes it", async () => {
    const api = fakeApi();
    render(<App api={api} initialProject="shop" />);

    await userEvent.click(await screen.findByRole('button', { name: flaky.test_id }));

    const panel = await screen.findByRole('region', { name: `History of ${flaky.test_id}` });
    const items = await within(panel).findAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('run-1');
    expect(items[0]).toHaveTextContent('failed');
    expect(items[0]).toHaveTextContent('AssertionError: 41 != 42');
    expect(items[1]).toHaveTextContent('passed');
    expect(api.fetchHistory).toHaveBeenCalledWith('shop', flaky.test_id, expect.anything());

    await userEvent.click(within(panel).getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('region', { name: /History of/ })).not.toBeInTheDocument();
  });

  it('ignores a slow response for a project that is no longer shown', async () => {
    const slow = deferred<VerdictsResponse>();
    const fetchVerdicts = vi.fn((project: string) =>
      project === 'old'
        ? slow.promise
        : Promise.resolve(verdictsResponse([verdict({ test_id: 'new::test' })])),
    );
    render(<App api={fakeApi({ fetchVerdicts })} initialProject="old" />);

    const input = screen.getByLabelText('Project');
    await userEvent.clear(input);
    await userEvent.type(input, 'new');
    await userEvent.click(screen.getByRole('button', { name: 'Load' }));
    await screen.findByRole('button', { name: 'new::test' });

    slow.resolve(verdictsResponse([verdict({ test_id: 'old::test' })]));
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByRole('button', { name: 'old::test' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'new::test' })).toBeInTheDocument();
  });
});
