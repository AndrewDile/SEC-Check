// Cross-team tester interface (tester-spec): POST /test/setup and GET /test/report.
// One session at a time: a successful setup wipes the database (like /reset) and makes
// its session_id the active one, replacing any earlier session. X-Session-ID on the
// project paths is ignored, since every call belongs to the active session.
// Errors use the tester's format {message, source}, not the Core {Error, Message}.
import express from 'express';

export const TEST_ERROR_SOURCE = 'system';

export function testError(res: express.Response, status: number, message: string) {
  return res.status(status).json({ message, source: TEST_ERROR_SOURCE });
}

export function testingRouter(wipe: () => Promise<void>): express.Router {
  const router = express.Router();
  let activeSession: string | undefined;
  let setupQueue: Promise<unknown> = Promise.resolve(); // setups run one after another

  router.post('/test/setup', async (req, res) => {
    const b = req.body;
    const sessionId = b?.session_id;
    if (typeof sessionId !== 'string' || !sessionId.trim() || sessionId.length > 255) {
      return testError(res, 400, 'session_id must be a non-empty string of at most 255 characters.');
    }
    if (b.setup !== undefined && (typeof b.setup !== 'object' || b.setup === null || Array.isArray(b.setup))) {
      return testError(res, 400, 'setup must be an object.');
    }
    const run = setupQueue.then(async () => {
      if (sessionId === activeSession) return 409;
      activeSession = undefined;   // the old session ends as soon as its data is wiped
      await wipe();
      activeSession = sessionId;
      return 201;
    });
    setupQueue = run.catch(() => undefined);
    try {
      const status = await run;
      if (status === 409) return testError(res, 409, `Session ${sessionId} is already active.`);
      return res.status(201).json({ session_id: sessionId });
    } catch (e) {
      console.error('test setup failed:', e);
      return testError(res, 500, 'Could not initialize the session database.');
    }
  });

  router.get('/test/report', (req, res) => {
    const sessionId = req.query.session_id;
    if (typeof sessionId !== 'string' || !sessionId) return testError(res, 400, 'The session_id query parameter is required.');
    if (sessionId !== activeSession) return testError(res, 404, `Unknown session ${sessionId}.`);
    res.json({
      session_id: sessionId,
      coverage: {
        code: { covered: null, total: null, basis: 'Code coverage is not measured by the Core API yet.' },
      },
    });
  });

  return router;
}
