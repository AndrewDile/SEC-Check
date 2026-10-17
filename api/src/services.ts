// Routes for the ingestion worker (/ingest) and notification service (/notif), and the calls the
// Core API makes to them. Contracts: ingestion_worker/ and notification_service/ *.openapi.yaml.
import { randomInt, timingSafeEqual } from 'node:crypto';
import express from 'express';
import { Database, DbError } from './db/api.js';

const COMPANY_ID = 'default';  // one company per deployment
const WORKER_URL = process.env.WORKER_URL;
const NOTIFIER_URL = process.env.NOTIFIER_URL;
const WEB_APP_URL = process.env.WEB_APP_URL ?? 'http://localhost:8000';

function requireToken(token: string | undefined): express.RequestHandler {
  return (req, res, next) => {
    const got = Buffer.from(req.get('authorization') ?? '');
    const want = Buffer.from(`Bearer ${token}`);
    if (!token || got.length !== want.length || !timingSafeEqual(got, want)) return res.status(401).end();
    next();
  };
}

// dp_name -> the worker's Dependency. "vendor:product", else split at the first space.
export function toWorkerDependency(name: string) {
  const at = name.includes(':') ? name.indexOf(':') : name.indexOf(' ');
  const vendor = (at < 0 ? name : name.slice(0, at)).trim();
  const product = (at < 0 ? name : name.slice(at + 1)).trim() || vendor;
  return { id: name, company_id: COMPANY_ID, vendor, product, version: null, cpe: null, purl: null, vendor_cik: null };
}

// Calls to the other services are retried, and each key's calls are sent in order.
const queues = new Map<string, Promise<void>>();

function send(key: string, what: string, url: string, init: RequestInit) {
  const job = async () => {
    for (let attempt = 1; ; attempt++) {
      try {
        const res = await fetch(url, init);
        if (res.ok) return;
        throw new Error(`HTTP ${res.status}`);
      } catch (e) {
        if (attempt === 5) return console.error(`${what} failed: ${e}`);
        await new Promise(r => setTimeout(r, 1000 * 2 ** attempt));
      }
    }
  };
  const next = (queues.get(key) ?? Promise.resolve()).then(job);
  queues.set(key, next);
  void next.then(() => { if (queues.get(key) === next) queues.delete(key); });
}

export const worker = {
  put(name: string) {
    if (!WORKER_URL) return;
    send(`dp:${name}`, `Worker PUT ${name}`, `${WORKER_URL}/dependencies/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { authorization: `Bearer ${process.env.INGEST_INBOUND_TOKEN}`, 'content-type': 'application/json' },
      body: JSON.stringify(toWorkerDependency(name)),
    });
  },
  delete(name: string) {
    if (!WORKER_URL) return;
    send(`dp:${name}`, `Worker DELETE ${name}`, `${WORKER_URL}/dependencies/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: { authorization: `Bearer ${process.env.INGEST_INBOUND_TOKEN}` },
    });
  },
};

async function notify(db: Database, incident: { id: string }) {
  if (!NOTIFIER_URL) return;
  const recipients = (await db.listTeams()).map(t => ({ recipient_id: `${t.name}:log`, team_name: t.name, channel: 'log', address: t.name }));
  send(`notif:${incident.id}`, `Notification ${incident.id}`, `${NOTIFIER_URL}/notifications`, {
    method: 'POST',
    headers: { authorization: `Bearer ${process.env.NOTIF_INBOUND_TOKEN}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      notification_id: incident.id,
      incident,
      claim_url: `${WEB_APP_URL}/app/#/incidents/${incident.id}`,
      recipients,
    }),
  });
  await db.logEvent(incident.id, 'NOTIFICATION_SENT', { recipients: recipients.map(r => r.recipient_id) });
}

export function servicesRouter(db: Database) {
  const router = express.Router();

  // Ingestion worker

  router.get('/ingest/dependencies', requireToken(process.env.INGEST_CORE_API_TOKEN), async (_req, res) => {
    res.json((await db.listDependencies()).map(toWorkerDependency));
  });

  router.post('/ingest/incidents', requireToken(process.env.INGEST_CORE_API_TOKEN), async (req, res) => {
    const body = req.body ?? {};
    for (const field of ['source', 'external_id', 'title', 'summary', 'source_url', 'detected_at']) {
      if (typeof body[field] !== 'string') throw new DbError('INVALID_DATA', `${field} is required.`);
    }
    const existing = await db.findIncidentBySource(body.source, body.external_id);
    if (existing) return res.status(200).json(existing.ingest);

    for (let attempt = 1; ; attempt++) {
      const id = String(randomInt(1e11, 1e12));  // 12-digit Incident_ID, like the web app's
      const stored = { ...body, id, created_at: new Date().toISOString() };
      try {
        await db.createIncident({
          incidentId: id,
          description: `${body.title}\n\n${body.summary}\n\nSource: ${body.source_url}`.slice(0, 5000),
          dependencyName: body.matched_dependencies?.[0]?.dependency_id,
          reportedAt: new Date(body.detected_at),
          source: body.source,
          externalId: body.external_id,
          ingest: stored,
        });
      } catch (e) {
        if (e instanceof DbError && e.type === 'UUID_EXISTS' && attempt < 5) continue;
        throw e;
      }
      await notify(db, stored);
      return res.status(201).json(stored);
    }
  });

  // Notification service

  router.post<{ id: string }>('/notif/notifications/:id/results', requireToken(process.env.NOTIF_CORE_API_TOKEN), async (req, res) => {
    const incident = await db.getIncident(req.params.id).catch(e => {
      if (e instanceof DbError && e.type === 'UUID_DNE') return undefined;
      throw e;
    });
    if (!incident?.source) return res.status(404).end();
    await db.logEvent(incident.incidentId, 'NOTIFICATION_RESULTS', req.body);
    res.status(200).end();
  });

  return router;
}
