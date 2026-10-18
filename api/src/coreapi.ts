import express from 'express';
import { DbError, type Incident, type Materiality, type Severity, type Ticket, type Urgency } from './db/api.js';
import { MySqlDb } from './db/mysql.js';
import { servicesRouter, worker } from './services.js';
import { testError, testingRouter } from './testing.js';

const db = MySqlDb.fromEnv();
const app = express();
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

// Validation ------------------------------------------------------------------

const MATERIALITY: Materiality[] = ['MATERIAL', 'IMMATERIAL', 'UNDECIDED'];
const SEVERITY: Severity[] = ['HIGH', 'MEDIUM', 'LOW', 'UNDECIDED', 'RESOLVED'];
const URGENCY: Urgency[] = ['URGENT', 'NOT_URGENT', 'UNDECIDED', 'RESOLVED'];

function invalid(message: string): never {
  throw new DbError('INVALID_DATA', message);
}

function oneOf<T extends string>(value: unknown, allowed: T[], field: string): T | undefined {
  if (value === undefined) return undefined;
  if (!allowed.includes(value as T)) invalid(`${field} must be one of ${allowed.join(', ')}.`);
  return value as T;
}

function timestamp(value: unknown): Date {
  const date = new Date(typeof value === 'string' ? value : NaN);
  if (Number.isNaN(date.getTime())) invalid('Timestamp must be an RFC 3339 date-time.');
  if (date.getTime() > Date.now() + 5000) invalid('Timestamp cannot be set in the future.');
  return date;
}

function description(value: unknown): string {
  if (typeof value !== 'string') invalid('Description is required.');
  if (value.length > 5000) invalid('Description must be at most 5000 characters.');
  return value;
}

function incidentId(value: unknown): string {
  if (typeof value !== 'string' || !value || value.includes('_') || value.length > 64)
    invalid('Incident_ID is invalid.');
  return value;
}

// "<incident>_<ticket>" or "<incident>_<ticket>_<version>"; a bare number needs incident
function ticketRef(value: unknown, incident?: string) {
  const parts = String(value ?? '').split('_');
  if (parts.length === 1 && incident) parts.unshift(incident);
  const [id, number, version] = parts;
  if (parts.length > 3 || !/^\d+$/.test(number ?? '') || (version !== undefined && !/^\d+$/.test(version)))
    invalid('Ticket_number is invalid.');
  if (incident && id !== incident) invalid('Ticket_number does not belong to Incident_ID.');
  return {
    incidentId: incidentId(id),
    ticketNumber: Number(number),
    version: version === undefined ? undefined : Number(version),
  };
}

function teamList(value: unknown, field: string): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || !value.every((t) => typeof t === 'string'))
    invalid(`${field} must be a list of team names.`);
  return value;
}

// Responses -------------------------------------------------------------------

function incidentOut(i: Incident, status?: string) {
  return {
    Incident_ID: i.incidentId,
    ...(status && { Status: status }),
    Description: i.description,
    ...(i.dependencyName && { Dependency: i.dependencyName }),
    Materiality: i.materiality,
    Severity: i.severity,
    Urgency: i.urgency,
    Timestamp: i.reportedAt.toISOString(),
  };
}

function ticketOut(t: Ticket, i: Incident, status?: string) {
  return {
    Incident_ID: t.incidentId,
    Ticket_ID: t.ticketId,
    Ticket_number: `${t.incidentId}_${t.ticketNumber}`,
    ...(status && { Status: status }),
    UUID_Description: i.description,
    Ticket_Description: t.description,
    Materiality_type: i.materiality,
    uuid_severity: i.severity,
    uuid_urgency: i.urgency,
    ticket_severity: t.severity,
    ticket_urgency: t.urgency,
    Team_List: t.teams,
    Ticket_Claim: t.claimedBy ? 'CLAIMED' : 'UNCLAIMED',
    ...(t.claimedBy && { Claimed_By: t.claimedBy }),
    Timestamp: t.reportedAt.toISOString(),
  };
}

// Pod contract v1.0.0 (all POST, Method in the body), plus the LIST methods the web app uses ------

app.post('/incidents', async (req, res) => {
  const b = req.body ?? {};
  if (b.Method === 'LIST') {
    return res.json({ Incidents: (await db.listIncidents()).map((i) => incidentOut(i)), Status: 'Listed' });
  }
  const id = incidentId(b.Incident_ID);
  timestamp(b.Timestamp);
  const fields = {
    materiality: oneOf(b.Materiality, MATERIALITY, 'Materiality'),
    severity: oneOf(b.Severity, SEVERITY, 'Severity'),
    urgency: oneOf(b.Urgency, URGENCY, 'Urgency'),
  };
  const dependency = b.Dependency ?? b.Dependency_Name;
  switch (b.Method) {
    case 'NEW': {
      const incident = await db.createIncident({
        incidentId: id,
        description: description(b.Description),
        dependencyName: dependency || undefined,
        reportedAt: timestamp(b.Timestamp),
        ...fields,
      });
      return res.json(incidentOut(incident, 'Created'));
    }
    case 'EDIT': {
      const incident = await db.editIncident(id, {
        description: description(b.Description),
        dependencyName: dependency,
        ...fields,
      });
      return res.json(incidentOut(incident, 'Edited'));
    }
    case 'GET':
      return res.json(incidentOut(await db.getIncident(id), 'Data Fetched'));
    default:
      invalid('Method must be one of NEW, EDIT, GET.');
  }
});

app.post('/tickets', async (req, res) => {
  const b = req.body ?? {};
  if (b.Method === 'LIST') {
    const claim = oneOf(b.Ticket_Claim, ['CLAIMED', 'UNCLAIMED'], 'Ticket_Claim');
    const tickets = (await db.listTickets())
      .filter((t) => !b.Team || t.teams.includes(b.Team))
      .filter((t) => !claim || (claim === 'CLAIMED') === Boolean(t.claimedBy));
    const incidents = new Map((await db.listIncidents()).map((i) => [i.incidentId, i]));
    return res.json({ Tickets: tickets.map((t) => ticketOut(t, incidents.get(t.incidentId)!)), Status: 'Listed' });
  }
  const id = incidentId(b.Incident_ID);
  const ts = timestamp(b.Timestamp);
  const fields = {
    severity: oneOf(b.Ticket_severity, SEVERITY, 'Ticket_severity'),
    urgency: oneOf(b.Ticket_urgency, URGENCY, 'Ticket_urgency'),
    teams: teamList(b.Team_list, 'Team_list'),
  };
  let ticket: Ticket;
  let status: string;
  switch (b.Method) {
    case 'NEW':
      ticket = await db.createTicket(id, { description: description(b.Description), reportedAt: ts, ...fields });
      status = 'Logged';
      break;
    case 'EDIT': {
      const ref = ticketRef(b.Ticket_number, id);
      ticket = await db.editTicket(id, ref.ticketNumber, { description: description(b.Description), ...fields });
      status = 'Edited';
      break;
    }
    case 'GET': {
      const ref = ticketRef(b.Ticket_number, id);
      ticket = await db.getTicket(id, ref.ticketNumber, ref.version);
      status = 'Displayed';
      break;
    }
    default:
      invalid('Method must be one of NEW, EDIT, GET.');
  }
  res.json(ticketOut(ticket, await db.getIncident(id), status));
});

app.post('/notifier', async (req, res) => {
  const b = req.body ?? {};
  const teams = teamList(b.Team_Names, 'Team_Names');
  if (!teams?.length) invalid('Team_Names invalid data type');
  const ref = ticketRef(b.Ticket_Number);
  if (ref.version !== undefined) invalid('Ticket_Number must be a ticket number without a version.');
  const known = new Set((await db.listTeams()).map((t) => t.name));
  const unknown = teams.filter((t) => !known.has(t));
  if (unknown.length) invalid(`Unknown team: ${unknown.join(', ')}.`);
  let status: string;
  switch (b.Method) {
    case 'NOTIFY':
      await db.notifyTeams(ref.incidentId, ref.ticketNumber, teams);
      status = 'Notified team';
      break;
    case 'CLAIM':
      if (teams.length !== 1) invalid('CLAIM takes exactly one team.');
      await db.claimTicket(ref.incidentId, ref.ticketNumber, teams[0]);
      status = 'Claimed ticket';
      break;
    default:
      invalid('Method must be one of CLAIM, NOTIFY.');
  }
  const uuid = /^\d{1,15}$/.test(ref.incidentId) ? Number(ref.incidentId) : ref.incidentId;
  res.json({ UUID: uuid, Ticket_Number: `${ref.incidentId}_${ref.ticketNumber}`, Status: status });
});

app.post('/logs', async (req, res) => {
  const b = req.body ?? {};
  const id = incidentId(b.Incident_ID);
  timestamp(b.Timestamp);
  const incident = await db.getIncident(id);
  res.json({
    Incident_ID: id,
    Description: incident.description,
    Materiality_type: incident.materiality,
    Severity: incident.severity,
    Urgency: incident.urgency,
    Ticket_ID_List: await db.listTicketIds(id),
    Status: 'Log Retrieved',
  });
});

// The spec spells it both ways
app.post(['/dependencies', '/dependancies'], async (req, res) => {
  const b = req.body ?? {};
  if (b.method === 'LIST') return res.json({ Dependencies: await db.listDependencies(), status: 'Listed' });
  if (typeof b.dp_name !== 'string' || !b.dp_name.trim() || b.dp_name.length > 255) invalid('dp_name is invalid.');
  const name: string = b.dp_name;
  switch (b.method) {
    case 'NEW':
      await db.addDependency(name, 'MANUAL');
      worker.put(name);
      return res.json({ dp_name: name, status: 'Added' });
    case 'MATCH':
      return res.json({ dp_name: name, status: (await db.hasDependency(name)) ? 'Exists' : 'Does not Exist' });
    case 'REMOVE':
      await db.removeDependency(name);
      worker.delete(name);
      return res.json({ dp_name: name, status: 'Removed' });
    default:
      invalid('method must be one of NEW, MATCH, REMOVE.');
  }
});

// Wipes the database and the worker's copy of the dependencies (/reset and /test/setup)
async function wipe() {
  const dependencies = await db.listDependencies();
  await db.reset();
  dependencies.forEach(worker.delete);
}

app.post('/reset', async (req, res) => {
  if (req.body?.method !== 'RESET') invalid('Method set to invalid data type');
  await wipe();
  res.json({ status: 'DB Wiped' });
});

// Cross-team tester interface: /test/setup, /test/report

app.use(testingRouter(wipe));

// Ingestion worker and notification service ----------------------------------

app.use(servicesRouter(db));

app.use(((err, req, res, _next) => {
  if (req.path.startsWith('/test/')) {
    if (err?.type === 'entity.parse.failed') return testError(res, 400, 'Body is not valid JSON.');
    console.error(err);
    return testError(res, 500, 'Unexpected error.');
  }
  if (err instanceof DbError)
    return res.status(err.type === 'TIMEOUT' ? 504 : 400).json({ Error: err.type, Message: err.message });
  if (err?.type === 'entity.parse.failed')
    return res.status(400).json({ Error: 'INVALID_DATA', Message: 'Body is not valid JSON.' });
  console.error(err);
  res.status(500).json({ Error: 'INTERNAL_ERROR', Message: 'Unexpected error.' });
}) as express.ErrorRequestHandler);

const port = Number(process.env.PORT ?? 3001);
app.listen(port, () => console.log(`Core API listening on :${port}`));
