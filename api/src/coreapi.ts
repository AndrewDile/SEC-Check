import { randomBytes, scryptSync } from 'node:crypto';
import express from 'express';
import { current, runIn, SERVICE_ACTORS, UNKNOWN } from './context.js';
import {
  DbError,
  type Incident,
  type Materiality,
  type Severity,
  type Ticket,
  type Urgency,
  type User,
} from './db/api.js';
import { migrate } from './db/migrate.js';
import { MySqlDb } from './db/mysql.js';
import { requestMetrics } from './metrics.js';
import { servicesRouter, worker } from './services.js';
import { testError, testSessions } from './testing.js';

// Headers a request may name its test session in; set SESSION_HEADERS to accept another team's convention too
const SESSION_HEADERS = (process.env.SESSION_HEADERS ?? 'x-session-id').split(',').map((h) => h.trim().toLowerCase());

await migrate();
const db = MySqlDb.fromEnv();
const sessions = testSessions(db);
const app = express();
app.set('trust proxy', 'loopback, uniquelocal'); // Caddy, so req.ip is the client
app.use(requestMetrics(SESSION_HEADERS));
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

// Cross-team tester interface: /test/setup, /test/report

app.use(sessions.router);

// Every other request runs in a scope (the real data, or its test session's) as an actor: the X-User header,
// which must be a user of that scope, a service (set by its token in services.ts), or Unknown.
app.use(async (req, _res, next) => {
  const session = SESSION_HEADERS.map((h) => req.get(h)).find(Boolean);
  const scope = session ? sessions.scope(session) : 0;
  if (scope === undefined) invalid(`Session ${session} is not active.`);
  const user = req.get('x-user');
  if (user !== undefined && !(await runIn({ scope, actor: UNKNOWN }, () => db.hasUser(user))))
    invalid(`Unknown user ${user}.`);
  runIn({ scope, actor: user ?? UNKNOWN, session }, next);
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

function optionalText(value: unknown, field: string, max: number): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || value.length > max)
    invalid(`${field} must be a string of at most ${max} characters.`);
  return value;
}

// Any non-empty string of at most 64 characters, '_' included: ticket numbers are read from the right
// (ticketRef, notifierTicket), since their ticket number and version are always digits.
function incidentId(value: unknown): string {
  if (typeof value !== 'string' || !value || value.length > 64) invalid('Incident_ID is invalid.');
  return value;
}

// /tickets: "<incident>_<ticket>", "<incident>_<ticket>_<version>" or a bare ticket number, for the request's
// Incident_ID. Reading it after that incident's own ID keeps it unambiguous when the ID contains '_'.
function ticketRef(value: unknown, incident: string) {
  const s = String(value ?? '');
  const rest = /^\d+$/.test(s) ? s : s.startsWith(`${incident}_`) ? s.slice(incident.length + 1) : undefined;
  if (rest === undefined) {
    if (/_\d+(_\d+)?$/.test(s)) invalid('Ticket_number does not belong to Incident_ID.');
    invalid('Ticket_number is invalid.');
  }
  const m = /^(\d+)(?:_(\d+))?$/.exec(rest);
  if (!m) invalid('Ticket_number is invalid.');
  return { ticketNumber: Number(m[1]), version: m[2] === undefined ? undefined : Number(m[2]) };
}

// /notifier: Ticket_Number is a weak ticket number, "<incident>_<ticket>"; the ticket is after the last '_'
function notifierTicket(value: unknown) {
  const m = /^(.+)_(\d+)$/.exec(String(value ?? ''));
  if (!m) invalid('Ticket_Number is invalid.');
  return { incidentId: incidentId(m[1]), ticketNumber: Number(m[2]) };
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
    ...(i.materiality === 'MATERIAL' && i.filingDeadline && { Filing_Deadline: i.filingDeadline }),
    Timestamp: i.reportedAt.toISOString(),
  };
}

function ticketOut(t: Ticket, status?: string) {
  const i = t.incident;
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

function userOut(u: User, status?: string) {
  return {
    Username: u.username,
    ...(u.displayName && { Display_Name: u.displayName }),
    ...(u.contactAddress && { Contact: u.contactAddress }),
    Contact_Channel: u.contactChannel,
    Teams: u.teams,
    ...(status && { Status: status }),
  };
}

// Pod contract v1.0.0 (all POST, Method in the body), plus the LIST methods the web app uses ------

app.post('/incidents', async (req, res) => {
  const b = req.body ?? {};
  if (b.Method === 'LIST') {
    const incidents = await db.listIncidents();
    await db.logEvent(undefined, 'INCIDENTS_LISTED', { count: incidents.length });
    return res.json({ Incidents: incidents.map((i) => incidentOut(i)), Status: 'Listed' });
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
      // Note: why, recorded in the audit log; required to change Materiality away from MATERIAL (extension)
      const note = optionalText(b.Note, 'Note', 5000);
      const incident = await db.editIncident(
        id,
        { description: description(b.Description), dependencyName: dependency, ...fields },
        note,
      );
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
    await db.logEvent(undefined, 'TICKETS_LISTED', { team: b.Team, claim, count: tickets.length });
    return res.json({ Tickets: tickets.map((t) => ticketOut(t)), Status: 'Listed' });
  }
  const id = incidentId(b.Incident_ID);
  const ts = timestamp(b.Timestamp);
  const fields = {
    severity: oneOf(b.Ticket_severity, SEVERITY, 'Ticket_severity'),
    urgency: oneOf(b.Ticket_urgency, URGENCY, 'Ticket_urgency'),
    teams: teamList(b.Team_list, 'Team_list'),
  };
  if (fields.teams?.length) await requireTeams(fields.teams, 'Team_list');
  switch (b.Method) {
    case 'NEW': {
      const ticket = await db.createTicket(id, { description: description(b.Description), reportedAt: ts, ...fields });
      return res.json(ticketOut(ticket, 'Logged'));
    }
    case 'EDIT': {
      const ref = ticketRef(b.Ticket_number, id);
      const ticket = await db.editTicket(id, ref.ticketNumber, { description: description(b.Description), ...fields });
      return res.json(ticketOut(ticket, 'Edited'));
    }
    case 'GET': {
      const ref = ticketRef(b.Ticket_number, id);
      return res.json(ticketOut(await db.getTicket(id, ref.ticketNumber, ref.version), 'Displayed'));
    }
    default:
      invalid('Method must be one of NEW, EDIT, GET.');
  }
});

app.post('/notifier', async (req, res) => {
  const b = req.body ?? {};
  const teams = teamList(b.Team_Names, 'Team_Names');
  if (!teams?.length) invalid('Team_Names invalid data type');
  const ref = notifierTicket(b.Ticket_Number);
  await requireTeams(teams, 'Team_Names');
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

// Audit_Log is an extension: the incident's audit entries, oldest first (AC-02, AC-04)
app.post('/logs', async (req, res) => {
  const b = req.body ?? {};
  const id = incidentId(b.Incident_ID);
  timestamp(b.Timestamp);
  const { incident, ticketIds, entries } = await db.getLog(id);
  res.json({
    Incident_ID: id,
    Description: incident.description,
    Materiality_type: incident.materiality,
    Severity: incident.severity,
    Urgency: incident.urgency,
    Ticket_ID_List: ticketIds,
    Audit_Log: entries.map((e) => ({
      Seq: e.seq,
      Timestamp: e.occurredAt.toISOString(),
      Event: e.eventType,
      Actor: e.actor ?? UNKNOWN,
      Details: e.payload,
    })),
    Status: 'Log Retrieved',
  });
});

// Teams: only teams created here (or the defaults /reset restores) can be used on tickets and in /notifier.
// GET and LIST are additions to the spec's NEW, REMOVE, ADD_USER, REMOVE_USER so teams can be read back.

async function requireTeams(names: string[], field: string) {
  const known = new Set((await db.listTeams()).map((t) => t.name));
  const unknown = names.filter((t) => !known.has(t));
  if (unknown.length) invalid(`${field} has unknown team: ${unknown.join(', ')}. Create it with /teams first.`);
}

function teamName(value: unknown): string {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim() || value.length > 64)
    invalid('Team_Name must be 1-64 characters without leading or trailing spaces.');
  return value;
}

function username(value: unknown): string {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim() || value.length > 64)
    invalid('Username must be 1-64 characters without leading or trailing spaces.');
  return value;
}

app.post('/teams', async (req, res) => {
  const b = req.body ?? {};
  if (b.Method === 'LIST')
    return res.json({ Team_List: (await db.listTeams()).map((t) => t.name), Status: 'Teams Listed' });
  const name = teamName(b.Team_Name);
  switch (b.Method === 'DELETE' ? 'REMOVE' : b.Method) {
    case 'NEW':
      await db.createTeam(name);
      return res.json({ Team_Name: name, Status: 'Created' });
    case 'REMOVE':
      await db.removeTeam(name);
      return res.json({ Team_Name: name, Status: 'Removed' });
    case 'GET':
      return res.json({ Team_Name: name, Members: (await db.getTeam(name)).members, Status: 'Team Received' });
    case 'ADD_USER': {
      const user = username(b.Username);
      await db.addMember(name, user);
      return res.json({ Team_Name: name, Username: user, Status: 'User added' });
    }
    case 'REMOVE_USER': {
      const user = username(b.Username);
      await db.removeMember(name, user);
      return res.json({ Team_Name: name, Username: user, Status: 'User removed' });
    }
    default:
      invalid('Method must be one of NEW, REMOVE, ADD_USER, REMOVE_USER, GET, LIST.');
  }
});

// Auth_Hash is stored salted and hashed again, since whatever the client sends works like a password
function credential(value: string) {
  const salt = randomBytes(16);
  return `scrypt$${salt.toString('hex')}$${scryptSync(value, salt, 32).toString('hex')}`;
}

// Users (contract v1.0.2): who can act through X-User, and where their notifications go (Contact). Add them
// to teams with /teams ADD_USER. GET, LIST, Display_Name and Contact_Channel are extensions. The service actors
// and Unknown can't be taken as usernames.
app.post('/users', async (req, res) => {
  const b = req.body ?? {};
  if (b.Method === 'LIST')
    return res.json({ Users: (await db.listUsers()).map((u) => userOut(u)), Status: 'Users Listed' });
  const name = username(b.Username);
  const authHash = optionalText(b.Auth_Hash, 'Auth_Hash', 1024);
  const fields = {
    displayName: optionalText(b.Display_Name, 'Display_Name', 255),
    contactChannel: optionalText(b.Contact_Channel, 'Contact_Channel', 32),
    contactAddress: optionalText(b.Contact, 'Contact', 255),
    authHash: authHash ? credential(authHash) : undefined,
  };
  if (fields.contactChannel === '') invalid('Contact_Channel must not be empty.');
  switch (b.Method === 'DELETE' ? 'REMOVE' : b.Method) {
    case 'NEW':
      if ([UNKNOWN, ...SERVICE_ACTORS].includes(name)) invalid(`${name} is reserved.`);
      if (!authHash) invalid('Auth_Hash is required when Method is NEW.');
      return res.json(userOut(await db.createUser({ username: name, ...fields }), 'Created'));
    case 'EDIT':
      return res.json(userOut(await db.editUser(name, fields), 'Edited'));
    case 'GET':
      return res.json(userOut(await db.getUser(name), 'User Received'));
    case 'REMOVE':
      await db.removeUser(name);
      return res.json({ Username: name, Status: 'Removed' });
    default:
      invalid('Method must be one of NEW, EDIT, GET, REMOVE, LIST.');
  }
});

// The spec spells it both ways. Only the real data's dependencies go to the ingestion worker.
app.post(['/dependencies', '/dependancies'], async (req, res) => {
  const b = req.body ?? {};
  const real = current().scope === 0;
  if (b.method === 'LIST') return res.json({ Dependencies: await db.listDependencies(), status: 'Listed' });
  if (typeof b.dp_name !== 'string' || !b.dp_name.trim() || b.dp_name.length > 255) invalid('dp_name is invalid.');
  const name: string = b.dp_name;
  switch (b.method) {
    case 'NEW':
      await db.addDependency(name, 'MANUAL');
      if (real) worker.put(name);
      return res.json({ dp_name: name, status: 'Added' });
    case 'MATCH':
      return res.json({ dp_name: name, status: (await db.hasDependency(name)) ? 'Exists' : 'Does not Exist' });
    case 'REMOVE':
      await db.removeDependency(name);
      if (real) worker.delete(name);
      return res.json({ dp_name: name, status: 'Removed' });
    default:
      invalid('method must be one of NEW, MATCH, REMOVE.');
  }
});

// Wipes the request's scope: a test session's data, or with no session the real data and the worker's copy
// of its dependencies
app.post('/reset', async (req, res) => {
  if (req.body?.method !== 'RESET') invalid('Method set to invalid data type');
  const dependencies = current().scope === 0 ? await db.listDependencies() : [];
  await db.reset();
  dependencies.forEach(worker.delete);
  res.json({ status: 'DB Wiped' });
});

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
