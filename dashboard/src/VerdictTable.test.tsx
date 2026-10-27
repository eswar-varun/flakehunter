import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { VerdictTable } from './VerdictTable';
import { verdict } from './test/fixtures';

const verdicts = [
  verdict({ test_id: 'tests/cart.py::test_total', status: 'broken', score: 0.61, failure_rate: 1 }),
  verdict({ test_id: 'tests/cart.py::test_discount', status: 'flaky', score: 0.21 }),
  verdict({ test_id: 'tests/user.py::test_login', status: 'flaky', score: 0.12 }),
];

function rows() {
  // The first row is the header.
  return screen.getAllByRole('row').slice(1);
}

describe('VerdictTable', () => {
  it('shows one row per test, in the order given, with its numbers', () => {
    render(<VerdictTable verdicts={verdicts} onSelect={() => {}} />);

    expect(rows()).toHaveLength(3);
    const first = within(rows()[0]);
    expect(first.getByText('broken')).toBeInTheDocument();
    expect(first.getByText('0.61')).toBeInTheDocument();
    expect(first.getByText('100%')).toBeInTheDocument();
    expect(first.getByText('2 / 8')).toBeInTheDocument();
    expect(first.getByText('1 / 3')).toBeInTheDocument();
    expect(first.getByRole('button', { name: 'tests/cart.py::test_total' })).toBeInTheDocument();
  });

  it('offers a filter per status with its count', () => {
    render(<VerdictTable verdicts={verdicts} onSelect={() => {}} />);

    expect(screen.getByRole('button', { name: 'All 3' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Broken 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Flaky 2' })).toBeInTheDocument();
    // Statuses with no tests get no button.
    expect(screen.queryByRole('button', { name: /Suspect/ })).not.toBeInTheDocument();
  });

  it('filters by status', async () => {
    render(<VerdictTable verdicts={verdicts} onSelect={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: 'Flaky 2' }));

    expect(screen.getByRole('button', { name: 'Flaky 2' })).toHaveAttribute('aria-pressed', 'true');
    expect(rows().map((r) => within(r).getByRole('button').textContent)).toEqual([
      'tests/cart.py::test_discount',
      'tests/user.py::test_login',
    ]);
  });

  it('filters by test name as you type', async () => {
    render(<VerdictTable verdicts={verdicts} onSelect={() => {}} />);

    await userEvent.type(screen.getByLabelText('Filter by test name'), 'login');

    expect(rows()).toHaveLength(1);
    expect(within(rows()[0]).getByRole('button')).toHaveTextContent('tests/user.py::test_login');
  });

  it('says so when the filter matches nothing', async () => {
    render(<VerdictTable verdicts={verdicts} onSelect={() => {}} />);

    await userEvent.type(screen.getByLabelText('Filter by test name'), 'nothing like this');

    expect(screen.getByText('No tests match this filter.')).toBeInTheDocument();
  });

  it('says so when there is nothing to triage', () => {
    render(<VerdictTable verdicts={[]} onSelect={() => {}} />);

    expect(screen.getByText('No broken, flaky or suspect tests.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('reports which test was chosen', async () => {
    const onSelect = vi.fn();
    render(<VerdictTable verdicts={verdicts} onSelect={onSelect} />);

    await userEvent.click(screen.getByRole('button', { name: 'tests/user.py::test_login' }));

    expect(onSelect).toHaveBeenCalledWith('tests/user.py::test_login');
  });

  it('marks the selected test', () => {
    render(
      <VerdictTable verdicts={verdicts} onSelect={() => {}} selected="tests/cart.py::test_total" />,
    );

    expect(rows()[0]).toHaveAttribute('aria-selected', 'true');
    expect(rows()[1]).toHaveAttribute('aria-selected', 'false');
  });
});
