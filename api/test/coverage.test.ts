import { describe, expect, it } from 'vitest';
import { coverageReport } from '../src/coverage.js';

describe('coverage report', () => {
  it('sums the services measured, and counts the ones reached', () => {
    const r = coverageReport(
      [
        { name: 'Core API', covered: 300, total: 1000 },
        { name: 'web app', covered: 0, total: 900 },
        { name: 'ingestion worker', missing: 'ENOTFOUND at /test/setup' },
        { name: 'notification service', covered: 20, total: 400 },
      ],
      ['run-2'],
    );
    expect(r.code).toEqual({
      covered: 320,
      total: 2300,
      basis:
        'Lines inside functions that ran between /test/setup and /test/report: Core API 300/1000, web app 0/900, ' +
        'notification service 20/400. Not measured: ingestion worker (ENOTFOUND at /test/setup). ' +
        'Sessions running at the same time also count: run-2.',
    });
    expect(r.component).toEqual({
      covered: 2,
      total: 3,
      basis:
        'Services with at least one line run: Core API, notification service. Not reached: web app. ' +
        'Not measured: ingestion worker (ENOTFOUND at /test/setup).',
    });
  });

  it('reports null when nothing was measured', () => {
    const r = coverageReport([{ name: 'Core API', missing: 'CODE_COVERAGE=off' }], []);
    expect(r.code).toMatchObject({ covered: null, total: null });
    expect(r.component).toMatchObject({ covered: null, total: null });
    expect(r.code.basis).toContain('Not measured: Core API (CODE_COVERAGE=off).');
  });
});
