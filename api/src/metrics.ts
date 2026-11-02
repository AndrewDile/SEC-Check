// Request timing: one JSON log line per request (see the logs at /logs/), and per test session a summary of
// each operation (path + Method) for its /test/report.
import type express from 'express';

const METHODS = new Set([
  'NEW',
  'EDIT',
  'GET',
  'LIST',
  'CLAIM',
  'NOTIFY',
  'MATCH',
  'REMOVE',
  'RESET',
  'ADD_USER',
  'REMOVE_USER',
]);
const MAX_SAMPLES = 10_000; // per operation per session

interface Samples {
  ms: number[];
  errors: number;
}

const sessions = new Map<string, Map<string, Samples>>();

const percentile = (sorted: number[], p: number) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
const round = (n: number) => Math.round(n * 100) / 100;

export const startSession = (id: string) => sessions.set(id, new Map());

export function endSession(id: string) {
  const ops = sessions.get(id) ?? new Map<string, Samples>();
  sessions.delete(id);
  return [...ops].map(([operation, { ms, errors }]) => {
    const sorted = [...ms].sort((a, b) => a - b);
    return {
      operation,
      count: ms.length,
      errors,
      p50_ms: round(percentile(sorted, 0.5)),
      p95_ms: round(percentile(sorted, 0.95)),
      max_ms: round(sorted.at(-1)!),
    };
  });
}

export function requestMetrics(sessionHeaders: string[]): express.RequestHandler {
  return (req, res, next) => {
    const start = process.hrtime.bigint();
    res.on('finish', () => {
      const ms = Number(process.hrtime.bigint() - start) / 1e6;
      const body = req.body ?? {};
      const method = body.Method ?? body.method;
      const route = req.route ? (typeof req.route.path === 'string' ? req.route.path : req.path) : 'unmatched';
      const operation = `${route} ${METHODS.has(method) ? method : req.method}`;
      const session = sessionHeaders.map((h) => req.get(h)).find(Boolean);
      console.log(
        JSON.stringify({
          at: new Date().toISOString(),
          operation,
          status: res.statusCode,
          ms: round(ms),
          ...(session && { session: session.slice(0, 255) }),
          ...(req.get('x-user') && { user: req.get('x-user')!.slice(0, 64) }),
        }),
      );
      const ops = session && sessions.get(session);
      if (!ops) return;
      const s = ops.get(operation) ?? { ms: [], errors: 0 };
      ops.set(operation, s);
      if (s.ms.length < MAX_SAMPLES) s.ms.push(ms);
      if (res.statusCode >= 400) s.errors++;
    });
    next();
  };
}
