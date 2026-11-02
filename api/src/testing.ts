// Cross-team tester interface (tester-spec): POST /test/setup and GET /test/report.
// Each session gets its own scope of the database (context.ts), so sessions run in parallel and never touch
// the real data. Requests join a session with the X-Session-ID header. /test/report ends the session and
// stores its report (code coverage and request timings); asking again returns the stored report.
// A session idle for SESSION_IDLE_MINUTES ends by itself, and an ended session's rows are deleted that long
// after it ends. Errors use the tester's format {message, source}, not the Core {Error, Message}.
import express from 'express';
import { linesSince, type Snapshot, snapshot } from './coverage.js';
import { type Database, DbError } from './db/api.js';
import * as metrics from './metrics.js';

export const TEST_ERROR_SOURCE = 'system';

const MAX_SESSIONS = Number(process.env.MAX_TEST_SESSIONS ?? 10);
const IDLE_MS = Number(process.env.SESSION_IDLE_MINUTES ?? 30) * 60_000;
const SETUPS_PER_MINUTE = Number(process.env.SETUPS_PER_MINUTE ?? 20); // per client IP

export function testError(res: express.Response, status: number, message: string) {
  return res.status(status).json({ message, source: TEST_ERROR_SOURCE });
}

interface Active {
  scope: number;
  coverage: Snapshot;
  overlapped: Set<string>;
  lastSeen: number;
  ending?: Promise<unknown>;
}

export function testSessions(db: Database) {
  const router = express.Router();
  const active = new Map<string, Active>();
  const setups = new Map<string, number[]>(); // client IP -> setup times in the last minute
  let starting = 0;

  async function end(id: string, s: Active, reason?: string) {
    s.ending ??= (async () => {
      const lines = await linesSince(s.coverage).catch((e) => console.error('code coverage failed:', e));
      const others = [...s.overlapped];
      const basis = !lines
        ? 'Code coverage could not be measured for this session.'
        : !lines.enabled
          ? 'Code coverage is turned off (CODE_COVERAGE=off).'
          : !lines.measured
            ? 'Code coverage is only measured when the Core API runs its compiled build.'
            : `Lines inside functions of the Core API's compiled build (dist/) that ran between /test/setup and /test/report.${
                others.length ? ` Sessions running at the same time also count: ${others.join(', ')}.` : ''
              }`;
      const measured = lines?.enabled && lines.measured;
      const report = {
        session_id: id,
        coverage: {
          code: { covered: measured ? lines.covered : null, total: measured ? lines.total : null, basis },
        },
        metrics: { requests: metrics.endSession(id), ...(reason && { ended: reason }) },
      };
      await db.endSession(s.scope, report);
      return report;
    })().finally(() => active.delete(id));
    return s.ending;
  }

  // Ends idle sessions and deletes the rows of sessions that ended long enough ago
  async function expire() {
    const now = Date.now();
    for (const [id, s] of active) if (now - s.lastSeen > IDLE_MS) await end(id, s, 'idle');
    const purged = await db.purgeEndedSessions(new Date(now - IDLE_MS));
    if (purged) console.log(`purged ${purged} ended test session(s)`);
  }
  void db.endOpenSessions().catch((e) => console.error('ending sessions left open:', e));
  setInterval(() => expire().catch((e) => console.error('session expiry failed:', e)), 60_000).unref();

  router.post('/test/setup', async (req, res) => {
    const b = req.body;
    const sessionId = b?.session_id;
    if (typeof sessionId !== 'string' || !sessionId.trim() || sessionId.length > 255) {
      return testError(res, 400, 'session_id must be a non-empty string of at most 255 characters.');
    }
    if (b.setup !== undefined && (typeof b.setup !== 'object' || b.setup === null || Array.isArray(b.setup))) {
      return testError(res, 400, 'setup must be an object.');
    }
    const ip = req.ip ?? 'unknown';
    const recent = (setups.get(ip) ?? []).filter((t) => Date.now() - t < 60_000);
    setups.set(ip, recent);
    if (recent.length >= SETUPS_PER_MINUTE)
      return testError(res, 429, 'Too many sessions set up; try again in a minute.');
    if (active.has(sessionId)) return testError(res, 409, `Session ${sessionId} is already active.`);
    if (active.size + starting >= MAX_SESSIONS)
      return testError(res, 429, `${MAX_SESSIONS} sessions are already running; try again later.`);
    recent.push(Date.now());
    starting++;
    try {
      const scope = await db.createSession(sessionId, ip);
      for (const s of active.values()) s.overlapped.add(sessionId);
      metrics.startSession(sessionId);
      active.set(sessionId, {
        scope,
        coverage: await snapshot(),
        overlapped: new Set(active.keys()),
        lastSeen: Date.now(),
      });
      return res.status(201).json({ session_id: sessionId });
    } catch (e) {
      if (e instanceof DbError && e.type === 'UUID_EXISTS') return testError(res, 409, e.message);
      console.error('test setup failed:', e);
      return testError(res, 500, 'Could not initialize the session database.');
    } finally {
      starting--;
    }
  });

  router.get('/test/report', async (req, res) => {
    const sessionId = req.query.session_id;
    if (typeof sessionId !== 'string' || !sessionId)
      return testError(res, 400, 'The session_id query parameter is required.');
    const s = active.get(sessionId);
    const report = s ? await end(sessionId, s) : await db.getSessionReport(sessionId);
    if (!report) return testError(res, 404, `Unknown session ${sessionId}.`);
    res.json(report);
  });

  // The scope of an active session, else undefined
  function scope(sessionId: string) {
    const s = active.get(sessionId);
    if (!s || s.ending) return undefined;
    s.lastSeen = Date.now();
    return s.scope;
  }

  return { router, scope };
}
