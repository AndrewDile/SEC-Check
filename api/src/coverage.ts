// Code coverage per test session: the Core API's own from V8's precise coverage (node:inspector, in-process, no
// port opened), plus the Python services' (servicesSince).
// Each take resets V8's counters, so per-character execution counts are summed here; a session's coverage is
// the lines of the compiled build (dist/) that ran between its setup snapshot and its report.
// V8 can't tell which request ran a line, so sessions that overlap share each other's lines.
import { readFileSync } from 'node:fs';
import { Session } from 'node:inspector/promises';
import { fileURLToPath } from 'node:url';

interface Script {
  source: string;
  counts: Float64Array; // summed execution count per character
  inFunction: Uint8Array; // 1 inside a function (top-level module code runs once at startup, so it's left out)
}

export type Snapshot = Map<string, Float64Array>;

const enabled = process.env.CODE_COVERAGE !== 'off';
const inspector = new Session();
const scripts = new Map<string, Script>();
let ready: Promise<unknown> = Promise.resolve();

if (enabled) {
  inspector.connect();
  ready = inspector
    .post('Profiler.enable')
    .then(() => inspector.post('Profiler.startPreciseCoverage', { callCount: true, detailed: true }));
}

const ours = (url: string) => url.startsWith('file:') && url.includes('/dist/') && !url.includes('/node_modules/');

async function take() {
  if (!enabled) return;
  await ready;
  const { result } = await inspector.post('Profiler.takePreciseCoverage');
  for (const { url, functions } of result.filter((s) => ours(s.url))) {
    let s = scripts.get(url);
    if (!s) {
      const source = readFileSync(fileURLToPath(url), 'utf8');
      s = { source, counts: new Float64Array(source.length), inFunction: new Uint8Array(source.length) };
      scripts.set(url, s);
    }
    // Inner ranges override outer ones, so fill from the largest down
    const ranges = functions
      .flatMap((f) => f.ranges)
      .sort((a, b) => b.endOffset - b.startOffset - (a.endOffset - a.startOffset));
    const counts = new Float64Array(s.source.length);
    for (const r of ranges) counts.fill(r.count, r.startOffset, r.endOffset);
    for (const f of functions) {
      const [r] = f.ranges;
      if (r.startOffset > 0 || r.endOffset < s.source.length) s.inFunction.fill(1, r.startOffset, r.endOffset);
    }
    for (let i = 0; i < counts.length; i++) s.counts[i] += counts[i];
  }
}

export async function snapshot(): Promise<Snapshot> {
  await take();
  return new Map([...scripts].map(([url, s]) => [url, s.counts.slice()]));
}

// Lines with code inside a function: covered if any of their characters ran since the snapshot
export async function linesSince(before: Snapshot) {
  await take();
  let covered = 0;
  let total = 0;
  for (const [url, s] of scripts) {
    const base = before.get(url);
    let start = 0;
    for (const line of s.source.split('\n')) {
      const end = start + line.length;
      const code = line.trim();
      if (code && !/^(\/\/|\/\*|\*)/.test(code) && !/^[\s})\];,]*$/.test(code)) {
        let inFunction = false;
        let ran = false;
        for (let i = start; i < end && !ran; i++) {
          if (!s.inFunction[i] || /\s/.test(s.source[i])) continue;
          inFunction = true;
          ran = s.counts[i] - (base?.[i] ?? 0) > 0;
        }
        if (inFunction) total++;
        if (ran) covered++;
      }
      start = end + 1;
    }
  }
  return { covered, total, enabled, measured: scripts.size > 0 };
}

// The Python services count their own lines (line_coverage.py) and report them over HTTP
const SERVICES = [
  { name: 'web app', url: process.env.WEB_APP_INTERNAL_URL, token: process.env.WEBAPP_INBOUND_TOKEN },
  { name: 'ingestion worker', url: process.env.WORKER_URL, token: process.env.INGEST_INBOUND_TOKEN },
  { name: 'notification service', url: process.env.NOTIFIER_URL, token: process.env.NOTIF_INBOUND_TOKEN },
];
const TIMEOUT_MS = 2000;

// When the snapshot was taken, and per service its generation, or why it failed
export type Marks = { at: number; services: Map<string, number | string> };

async function call(s: (typeof SERVICES)[number], path: string, method = 'GET') {
  const res = await fetch(`${s.url}${path}`, {
    method,
    headers: { authorization: `Bearer ${s.token}` },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// e.g. "HTTP 401", "HTTP 409" (restarted since the snapshot), "ENOTFOUND", "no answer in 2000 ms"
function reason(e: unknown) {
  const err = e as { name?: string; message?: string; cause?: { code?: string; message?: string } };
  if (err.name === 'TimeoutError') return `no answer in ${TIMEOUT_MS} ms`;
  return err.cause?.code ?? err.cause?.message ?? err.message ?? String(e); // fetch's own is "fetch failed"
}

export async function snapshotServices(): Promise<Marks> {
  const marks: Marks = { at: Date.now(), services: new Map() };
  await Promise.all(
    SERVICES.filter((s) => s.url).map(async (s) => {
      let mark: number | string;
      try {
        const r = await call(s, '/coverage/snapshot', 'POST');
        mark = Number.isSafeInteger(r?.since) ? r.since : 'malformed reply';
      } catch (e) {
        mark = reason(e);
      }
      if (typeof mark === 'string') console.error(`coverage: ${s.name}: ${mark}`);
      marks.services.set(s.name, mark);
    }),
  );
  return marks;
}

// A service's lines since its snapshot, or why they weren't measured
type Measured = { name: string; covered: number; total: number };
export type Part = Measured | { name: string; missing: string };

// /test/report's code coverage (lines of every service measured, summed) and component coverage (services reached)
export function coverageReport(parts: Part[], overlapped: string[]) {
  const measured = parts.filter((p): p is Measured => 'covered' in p);
  const missing = parts.flatMap((p) => ('missing' in p ? [`${p.name} (${p.missing})`] : []));
  const names = (ps: Measured[]) => ps.map((p) => p.name).join(', ');
  const reached = measured.filter((p) => p.covered > 0);
  const unreached = measured.filter((p) => p.covered === 0);
  const notMeasured = missing.length ? ` Not measured: ${missing.join(', ')}.` : '';
  const any = measured.length > 0;
  return {
    code: {
      covered: any ? measured.reduce((n, p) => n + p.covered, 0) : null,
      total: any ? measured.reduce((n, p) => n + p.total, 0) : null,
      basis:
        `Lines inside functions that ran between /test/setup and /test/report: ${
          measured.map((p) => `${p.name} ${p.covered}/${p.total}`).join(', ') || 'none measured'
        }.${notMeasured}` +
        (overlapped.length ? ` Sessions running at the same time also count: ${overlapped.join(', ')}.` : ''),
    },
    component: {
      covered: any ? reached.length : null,
      total: any ? measured.length : null,
      basis:
        `Services with at least one line run: ${names(reached) || 'none'}.` +
        (unreached.length ? ` Not reached: ${names(unreached)}.` : '') +
        notMeasured,
    },
  };
}

export function servicesSince(marks: Marks): Promise<Part[]> {
  return Promise.all(
    SERVICES.map(async (s): Promise<Part> => {
      const mark = marks.services.get(s.name);
      if (!s.url || mark === undefined) return { name: s.name, missing: 'not configured' };
      if (typeof mark === 'string') {
        // Not up at /test/setup: if it started counting after that, everything it ran counts
        const r = await call(s, '/coverage?since=0').catch(() => undefined);
        const started = typeof r?.started === 'number' ? r.started * 1000 : 0;
        return started >= marks.at ? measured(s.name, r) : { name: s.name, missing: `${mark} at /test/setup` };
      }
      try {
        return measured(s.name, await call(s, `/coverage?since=${mark}`));
      } catch (e) {
        console.error(`coverage: ${s.name}: ${reason(e)}`);
        return { name: s.name, missing: `${reason(e)} at /test/report` };
      }
    }),
  );
}

function measured(name: string, r: { enabled?: unknown; covered?: unknown; total?: unknown } | null): Part {
  const { enabled, covered, total } = r ?? {};
  if (enabled === false) return { name, missing: 'CODE_COVERAGE=off' };
  if (typeof covered !== 'number' || typeof total !== 'number') return { name, missing: 'malformed reply' };
  if (!Number.isSafeInteger(covered) || !Number.isSafeInteger(total) || covered > total)
    return { name, missing: 'malformed reply' };
  return { name, covered, total };
}
