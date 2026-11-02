// Code coverage per test session from V8's precise coverage (node:inspector, in-process, no port opened).
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
