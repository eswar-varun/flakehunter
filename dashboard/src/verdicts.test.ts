import { describe, expect, it } from 'vitest';
import { countByStatus, filterVerdicts, percent, shortSha } from './verdicts';
import { verdict } from './test/fixtures';

const verdicts = [
  verdict({ test_id: 'tests/cart.py::test_total', status: 'broken' }),
  verdict({ test_id: 'tests/cart.py::test_discount', status: 'flaky' }),
  verdict({ test_id: 'tests/user.py::test_login', status: 'flaky' }),
  verdict({ test_id: 'tests/user.py::test_logout', status: 'suspect' }),
];

describe('filterVerdicts', () => {
  it('keeps everything for "all" and an empty query', () => {
    expect(filterVerdicts(verdicts, { status: 'all', query: '' })).toEqual(verdicts);
  });

  it('filters by status', () => {
    const ids = filterVerdicts(verdicts, { status: 'flaky', query: '' }).map((v) => v.test_id);

    expect(ids).toEqual(['tests/cart.py::test_discount', 'tests/user.py::test_login']);
  });

  it('matches the query anywhere in the test id, ignoring case and surrounding spaces', () => {
    const ids = filterVerdicts(verdicts, { status: 'all', query: '  USER.py ' }).map(
      (v) => v.test_id,
    );

    expect(ids).toEqual(['tests/user.py::test_login', 'tests/user.py::test_logout']);
  });

  it('applies status and query together', () => {
    const ids = filterVerdicts(verdicts, { status: 'flaky', query: 'cart' }).map((v) => v.test_id);

    expect(ids).toEqual(['tests/cart.py::test_discount']);
  });

  it('keeps the order it was given, which is the API ranking', () => {
    const reversed = [...verdicts].reverse();

    expect(filterVerdicts(reversed, { status: 'all', query: '' })).toEqual(reversed);
  });
});

describe('countByStatus', () => {
  it('counts every status, including ones with no tests', () => {
    expect(countByStatus(verdicts)).toEqual({
      broken: 1,
      flaky: 2,
      suspect: 1,
      stable: 0,
      skipped: 0,
    });
  });
});

describe('percent', () => {
  it.each([
    [0, '0%'],
    [0.004, '<1%'],
    [0.2345, '23%'],
    [1, '100%'],
  ])('formats %f as %s', (rate, text) => {
    expect(percent(rate)).toBe(text);
  });
});

describe('shortSha', () => {
  it('shortens long commit hashes and leaves short names alone', () => {
    expect(shortSha('4d6cdd6f0e8b2a1c9d3e5f7a8b9c0d1e2f3a4b5c')).toBe('4d6cdd6');
    expect(shortSha('c1')).toBe('c1');
  });
});
