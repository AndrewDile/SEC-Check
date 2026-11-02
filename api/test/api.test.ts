// HTTP tests for the pod contract (v1.0.0) against any deployed Core API. WIPES its data via /reset.
// Runs only when API_URL is set, e.g.:
//   API_URL=http://localhost:3001 npm run test:api
// The /ingest tests are ours (not in the pod contract) and also need INGEST_CORE_API_TOKEN.
import { beforeEach, describe, expect, it } from 'vitest';
import { newYorkDate } from '../src/calendar.js';

const API = process.env.API_URL;
const INGEST_TOKEN = process.env.INGEST_CORE_API_TOKEN;
const TS = '2026-09-25T20:00:00Z';
const ID = '102356304331';

type Headers = Record<string, string>;

async function post(path: string, body: unknown, headers: Headers = {}) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await res.json() };
}

const newIncident = (id = ID, extra = {}, headers: Headers = {}) =>
  post(
    '/incidents',
    { Incident_ID: id, Method: 'NEW', Timestamp: TS, Description: 'Critical API gateway timeout.', ...extra },
    headers,
  );
const getIncident = (id = ID, headers: Headers = {}) =>
  post('/incidents', { Incident_ID: id, Method: 'GET', Timestamp: TS, Description: '' }, headers);
const editIncident = (extra = {}, headers: Headers = {}) =>
  post('/incidents', { Incident_ID: ID, Method: 'EDIT', Timestamp: TS, Description: 'Updated.', ...extra }, headers);
const newTicket = (id = ID, extra = {}, headers: Headers = {}) =>
  post(
    '/tickets',
    { Incident_ID: id, Method: 'NEW', Timestamp: TS, Description: 'Initial triage.', ...extra },
    headers,
  );
const auditLog = async (headers: Headers = {}) =>
  (await post('/logs', { Incident_ID: ID, Timestamp: TS }, headers)).body.Audit_Log as {
    Event: string;
    Actor: string;
    Details: Record<string, unknown>;
  }[];

function expectError(r: { status: number; body: { Error?: string } }, error: string) {
  expect(r.status).toBe(400);
  expect(r.body.Error).toBe(error);
}

describe.skipIf(!API)('Core API pod contract', () => {
  beforeEach(async () => {
    expect((await post('/reset', { method: 'RESET' })).body).toEqual({ status: 'DB Wiped' });
  });

  describe('/reset', () => {
    it('rejects an unknown method', async () => {
      expectError(await post('/reset', { method: 'PUPPY' }), 'INVALID_DATA');
    });
  });

  describe('/incidents', () => {
    it('creates, fetches and edits (REQ-01, REQ-03)', async () => {
      const created = await newIncident(undefined, {
        Materiality: 'MATERIAL',
        Severity: 'HIGH',
        Urgency: 'URGENT',
        Dependency: 'auth-service-v2',
      });
      expect(created.status).toBe(200);
      expect(created.body).toMatchObject({
        Incident_ID: ID,
        Status: 'Created',
        Materiality: 'MATERIAL',
        Severity: 'HIGH',
        Urgency: 'URGENT',
      });

      expect((await getIncident()).body).toMatchObject({
        Status: 'Data Fetched',
        Description: 'Critical API gateway timeout.',
        Dependency: 'auth-service-v2',
      });

      const edited = await editIncident({ Materiality: 'IMMATERIAL', Note: 'Re-assessed.' });
      expect(edited.body).toMatchObject({
        Status: 'Edited',
        Description: 'Updated.',
        Materiality: 'IMMATERIAL',
        Severity: 'HIGH',
      });
    });

    it('defaults decisions to UNDECIDED', async () => {
      expect((await newIncident()).body).toMatchObject({
        Materiality: 'UNDECIDED',
        Severity: 'UNDECIDED',
        Urgency: 'UNDECIDED',
      });
    });

    it('rejects a duplicate or unknown Incident_ID', async () => {
      await newIncident();
      expectError(await newIncident(), 'UUID_EXISTS');
      expectError(await getIncident('000000000001'), 'UUID_DNE');
    });

    it('rejects invalid data', async () => {
      expectError(await newIncident(undefined, { Timestamp: '2999-01-01T00:00:00Z' }), 'INVALID_DATA');
      expectError(await newIncident(undefined, { Severity: 'EXTREME' }), 'INVALID_DATA');
      expectError(await newIncident(undefined, { Description: 'x'.repeat(5001) }), 'INVALID_DATA');
      expectError(
        await post('/incidents', { Incident_ID: '1', Method: 'DELETE', Timestamp: TS, Description: '' }),
        'INVALID_DATA',
      );
    });

    it('starts the filing deadline at the first MATERIAL determination and never restarts it (REQ-04)', async () => {
      await newIncident();
      expect((await getIncident()).body.Filing_Deadline).toBeUndefined();
      const deadline = (await editIncident({ Materiality: 'MATERIAL' })).body.Filing_Deadline;
      expect(deadline).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(deadline > newYorkDate(new Date())).toBe(true);
      expect([0, 6]).not.toContain(new Date(`${deadline}T00:00:00Z`).getUTCDay());

      expect((await editIncident({ Materiality: 'IMMATERIAL' })).body.Message).toMatch(/Note/);
      const reversed = await editIncident({ Materiality: 'IMMATERIAL', Note: 'Contained before any data left.' });
      expect(reversed.body.Filing_Deadline).toBeUndefined();
      expect((await editIncident({ Materiality: 'MATERIAL' })).body.Filing_Deadline).toBe(deadline);

      const reversal = (await auditLog()).find((e) => e.Event === 'MATERIALITY_REVERSED');
      expect(reversal?.Details).toEqual({
        before: { description: 'Updated.', materiality: 'MATERIAL' },
        after: { description: 'Updated.', materiality: 'IMMATERIAL' },
        note: 'Contained before any data left.',
      });
    });
  });

  describe('/tickets', () => {
    beforeEach(() => newIncident());

    it('logs a ticket with a strong ID and the incident fields (REQ-02)', async () => {
      const r = await newTicket(undefined, {
        Ticket_severity: 'HIGH',
        Ticket_urgency: 'URGENT',
        Team_list: ['CYBER1', 'LEGAL'],
      });
      expect(r.status).toBe(200);
      expect(r.body).toMatchObject({
        Incident_ID: ID,
        Ticket_ID: `${ID}_1_1`,
        Status: 'Logged',
        UUID_Description: 'Critical API gateway timeout.',
        Ticket_Description: 'Initial triage.',
        Materiality_type: 'UNDECIDED',
        ticket_severity: 'HIGH',
        ticket_urgency: 'URGENT',
        Ticket_Claim: 'UNCLAIMED',
      });
      expect([...r.body.Team_List].sort()).toEqual(['CYBER1', 'LEGAL']);
    });

    it('keeps old versions when a ticket is edited', async () => {
      await newTicket();
      const edited = await post('/tickets', {
        Incident_ID: ID,
        Method: 'EDIT',
        Timestamp: TS,
        Ticket_number: `${ID}_1`,
        Description: 'Second look.',
      });
      expect(edited.body).toMatchObject({ Ticket_ID: `${ID}_1_2`, Status: 'Edited' });

      const latest = await post('/tickets', {
        Incident_ID: ID,
        Method: 'GET',
        Timestamp: TS,
        Ticket_number: `${ID}_1`,
      });
      expect(latest.body).toMatchObject({
        Ticket_ID: `${ID}_1_2`,
        Status: 'Displayed',
        Ticket_Description: 'Second look.',
      });

      // a strong ID, as /logs lists them, gives that version (LIM-05)
      const first = await post('/tickets', {
        Incident_ID: ID,
        Method: 'GET',
        Timestamp: TS,
        Ticket_number: `${ID}_1_1`,
      });
      expect(first.body.Ticket_Description).toBe('Initial triage.');
    });

    it('rejects unknown incidents and tickets', async () => {
      expectError(await newTicket('000000000001'), 'UUID_DNE');
      expectError(
        await post('/tickets', { Incident_ID: ID, Method: 'GET', Timestamp: TS, Ticket_number: `${ID}_9` }),
        'UUID_DNE',
      );
    });

    it('lists the latest version of every ticket', async () => {
      await newTicket(undefined, { Team_list: ['LEGAL'] });
      await newTicket();
      await post('/tickets', {
        Incident_ID: ID,
        Method: 'EDIT',
        Timestamp: TS,
        Ticket_number: `${ID}_1`,
        Description: 'v2',
      });
      const r = await post('/tickets', { Method: 'LIST' });
      expect(r.body.Tickets.map((t: { Ticket_ID: string }) => t.Ticket_ID)).toEqual([`${ID}_1_2`, `${ID}_2_1`]);
      expect(r.body.Tickets[0]).toMatchObject({
        Team_List: ['LEGAL'],
        UUID_Description: 'Critical API gateway timeout.',
      });
    });
  });

  describe('/notifier', () => {
    beforeEach(async () => {
      await newIncident();
      await newTicket();
    });

    it('notifies teams and lets one team claim (REQ-04)', async () => {
      const notified = await post('/notifier', {
        Team_Names: ['CYBER1', 'CYBER2'],
        Method: 'NOTIFY',
        Ticket_Number: `${ID}_1`,
      });
      expect(notified.body).toEqual({ UUID: 102356304331, Ticket_Number: `${ID}_1`, Status: 'Notified team' });

      const claimed = await post('/notifier', { Team_Names: ['CYBER1'], Method: 'CLAIM', Ticket_Number: `${ID}_1` });
      expect(claimed.body.Status).toBe('Claimed ticket');
      expectError(
        await post('/notifier', { Team_Names: ['CYBER2'], Method: 'CLAIM', Ticket_Number: `${ID}_1` }),
        'INVALID_DATA',
      );

      const ticket = await post('/tickets', {
        Incident_ID: ID,
        Method: 'GET',
        Timestamp: TS,
        Ticket_number: `${ID}_1`,
      });
      expect(ticket.body.Ticket_Claim).toBe('CLAIMED');
    });

    it('lets only one of two teams claiming at once win', async () => {
      const claim = (team: string) =>
        post('/notifier', { Team_Names: [team], Method: 'CLAIM', Ticket_Number: `${ID}_1` });
      const results = await Promise.all([claim('CYBER1'), claim('CYBER2')]);
      expect(results.map((r) => r.status).sort()).toEqual([200, 400]);
    });

    it('rejects empty or unknown teams', async () => {
      expectError(
        await post('/notifier', { Team_Names: [], Method: 'CLAIM', Ticket_Number: `${ID}_1` }),
        'INVALID_DATA',
      );
      expectError(
        await post('/notifier', { Team_Names: ['NOPE'], Method: 'NOTIFY', Ticket_Number: `${ID}_1` }),
        'INVALID_DATA',
      );
    });
  });

  describe('Incident_IDs with underscores', () => {
    const UID = 'INC_2026_001';
    const ticket = (method: string, number: string, extra = {}, id = UID) =>
      post('/tickets', { Incident_ID: id, Method: method, Timestamp: TS, Ticket_number: number, ...extra });

    it('stores and fetches the incident, its tickets and its log', async () => {
      expect((await newIncident(UID)).body).toMatchObject({ Incident_ID: UID, Status: 'Created' });
      expect((await getIncident(UID)).body).toMatchObject({ Incident_ID: UID, Status: 'Data Fetched' });
      expect((await newTicket(UID)).body).toMatchObject({ Ticket_ID: `${UID}_1_1`, Status: 'Logged' });
      expect((await ticket('EDIT', `${UID}_1`, { Description: 'v2' })).body.Ticket_ID).toBe(`${UID}_1_2`);
      expect((await ticket('GET', `${UID}_1`)).body.Ticket_Description).toBe('v2');
      expect((await ticket('GET', `${UID}_1_1`)).body.Ticket_Description).toBe('Initial triage.');
      expect((await ticket('GET', '1')).body.Ticket_ID).toBe(`${UID}_1_2`);
      const log = await post('/logs', { Incident_ID: UID, Timestamp: TS });
      expect(log.body.Ticket_ID_List).toEqual([`${UID}_1_1`, `${UID}_1_2`]);
    });

    it('notifies and claims by the weak ticket number', async () => {
      await newIncident(UID);
      await newTicket(UID);
      const notified = await post('/notifier', {
        Team_Names: ['CYBER1'],
        Method: 'NOTIFY',
        Ticket_Number: `${UID}_1`,
      });
      expect(notified.body).toEqual({ UUID: UID, Ticket_Number: `${UID}_1`, Status: 'Notified team' });
      const claimed = await post('/notifier', { Team_Names: ['CYBER1'], Method: 'CLAIM', Ticket_Number: `${UID}_1` });
      expect(claimed.body.Status).toBe('Claimed ticket');
      expect((await ticket('GET', `${UID}_1`)).body.Claimed_By).toBe('CYBER1');
    });

    it('keeps incidents A and A_1 apart', async () => {
      await newIncident('A');
      await newIncident('A_1');
      await newTicket('A', { Description: 'ticket of A' });
      await newTicket('A_1', { Description: 'ticket of A_1' });
      // With Incident_ID given, A_1_1 is version 1 of ticket 1 of A
      expect((await ticket('GET', 'A_1_1', {}, 'A')).body.Ticket_Description).toBe('ticket of A');
      expect((await ticket('GET', 'A_1_1', {}, 'A_1')).body.Ticket_Description).toBe('ticket of A_1');
      // /notifier reads A_1_1 as ticket 1 of A_1
      const r = await post('/notifier', { Team_Names: ['LEGAL'], Method: 'NOTIFY', Ticket_Number: 'A_1_1' });
      expect(r.body).toMatchObject({ UUID: 'A_1', Ticket_Number: 'A_1_1' });
    });

    it('still rejects a ticket number of another incident, and bad IDs', async () => {
      await newIncident(UID);
      await newTicket(UID);
      expectError(await ticket('GET', 'OTHER_1'), 'INVALID_DATA');
      expectError(await ticket('GET', `${UID}_x`), 'INVALID_DATA');
      expectError(await newIncident(''), 'INVALID_DATA');
      expectError(await newIncident('x'.repeat(65)), 'INVALID_DATA');
      // no ticket number after the last '_'
      expectError(
        await post('/notifier', { Team_Names: ['LEGAL'], Method: 'NOTIFY', Ticket_Number: 'INC_x' }),
        'INVALID_DATA',
      );
    });
  });

  describe('/logs', () => {
    it('lists every ticket version in order (REQ-06)', async () => {
      await newIncident(undefined, { Materiality: 'MATERIAL' });
      await newTicket();
      await newTicket();
      await post('/tickets', {
        Incident_ID: ID,
        Method: 'EDIT',
        Timestamp: TS,
        Ticket_number: `${ID}_1`,
        Description: 'Edit.',
      });
      const r = await post('/logs', { Incident_ID: ID, Timestamp: TS });
      expect(r.body).toMatchObject({
        Incident_ID: ID,
        Materiality_type: 'MATERIAL',
        Status: 'Log Retrieved',
        Ticket_ID_List: [`${ID}_1_1`, `${ID}_2_1`, `${ID}_1_2`],
      });
    });

    it('returns the audit log with who did what, reads included (REQ-02, AC-02)', async () => {
      await newIncident(undefined, {}, { 'x-user': 'alice' });
      await newTicket(undefined, {}, { 'x-user': 'carol' });
      await getIncident();
      await post(
        '/notifier',
        { Team_Names: ['LEGAL'], Method: 'NOTIFY', Ticket_Number: `${ID}_1` },
        { 'x-user': 'dana' },
      );
      expect((await auditLog()).map((e) => [e.Event, e.Actor])).toEqual([
        ['INCIDENT_CREATED', 'alice'],
        ['TICKET_CREATED', 'carol'], // no INCIDENT_READ for reading the incident into the ticket response
        ['INCIDENT_READ', 'Unknown'],
        ['TEAMS_NOTIFIED', 'dana'],
      ]);
      expect((await auditLog()).at(-1)).toMatchObject({ Event: 'LOG_READ' });
    });

    it('rejects a user that does not exist, or that is a service', async () => {
      expectError(await newIncident(undefined, {}, { 'x-user': 'mallory' }), 'INVALID_DATA');
      expectError(await newIncident(undefined, {}, { 'x-user': 'ingestion-worker' }), 'INVALID_DATA');
      expectError(await newIncident(undefined, {}, { 'x-user': 'Unknown' }), 'INVALID_DATA');
    });

    it('rejects a future timestamp and unknown incidents', async () => {
      await newIncident();
      expectError(await post('/logs', { Incident_ID: ID, Timestamp: '2999-09-25T20:30:00Z' }), 'INVALID_DATA');
      expectError(await post('/logs', { Incident_ID: '000000000001', Timestamp: TS }), 'UUID_DNE');
    });
  });

  describe('/dependencies', () => {
    it('adds, matches and removes (REQ-05)', async () => {
      expect((await post('/dependencies', { dp_name: 'auth-service-v2', method: 'NEW' })).body).toEqual({
        dp_name: 'auth-service-v2',
        status: 'Added',
      });
      expectError(await post('/dependencies', { dp_name: 'auth-service-v2', method: 'NEW' }), 'DP_EXISTS');
      expect((await post('/dependencies', { dp_name: 'auth-service-v2', method: 'MATCH' })).body.status).toBe('Exists');
      expect((await post('/dependencies', { dp_name: 'auth-service-v2', method: 'REMOVE' })).body.status).toBe(
        'Removed',
      );
      expect((await post('/dependencies', { dp_name: 'auth-service-v2', method: 'MATCH' })).body.status).toBe(
        'Does not Exist',
      );
      expectError(await post('/dependencies', { dp_name: 'auth-service-v2', method: 'REMOVE' }), 'DP_DNE');
    });

    it('also answers at the /dependancies spelling', async () => {
      expect((await post('/dependancies', { dp_name: 'x', method: 'NEW' })).body.status).toBe('Added');
    });
  });

  describe('/teams', () => {
    const teams = (body: Record<string, unknown>) => post('/teams', body);
    const names = async () => (await teams({ Method: 'LIST' })).body.Team_List;
    const members = async (team: string) => [...(await teams({ Team_Name: team, Method: 'GET' })).body.Members].sort();

    it('starts with the default teams after a reset', async () => {
      expect((await teams({ Method: 'LIST' })).body).toEqual({
        Team_List: ['LEGAL', 'CYBER1', 'CYBER2'],
        Status: 'Teams Listed',
      });
    });

    it('creates, fetches and removes a team', async () => {
      expect(await teams({ Team_Name: 'Red Team', Method: 'NEW' })).toEqual({
        status: 200,
        body: { Team_Name: 'Red Team', Status: 'Created' },
      });
      expect((await teams({ Team_Name: 'Red Team', Method: 'GET' })).body).toEqual({
        Team_Name: 'Red Team',
        Members: [],
        Status: 'Team Received',
      });
      expect(await names()).toContain('Red Team');
      expect((await teams({ Team_Name: 'Red Team', Method: 'REMOVE' })).body).toEqual({
        Team_Name: 'Red Team',
        Status: 'Removed',
      });
      expect(await names()).not.toContain('Red Team');
    });

    it('rejects duplicates, unknown teams and bad input', async () => {
      expectError(await teams({ Team_Name: 'LEGAL', Method: 'NEW' }), 'TEAM_EXISTS');
      expectError(await teams({ Team_Name: 'GHOST', Method: 'GET' }), 'TEAM_DNE');
      expectError(await teams({ Team_Name: 'GHOST', Method: 'REMOVE' }), 'TEAM_DNE');
      expectError(await teams({ Team_Name: ' padded', Method: 'NEW' }), 'INVALID_DATA');
      expectError(await teams({ Team_Name: '', Method: 'NEW' }), 'INVALID_DATA');
      expectError(await teams({ Team_Name: 'X', Method: 'RENAME' }), 'INVALID_DATA');
      expectError(await teams({ Team_Name: 'LEGAL', Method: 'ADD_USER' }), 'INVALID_DATA');
    });

    it('starts with the default members, and adds and removes them', async () => {
      expect(await members('LEGAL')).toEqual(['carol', 'core-gateway', 'dana']);
      expect((await teams({ Team_Name: 'LEGAL', Method: 'ADD_USER', Username: 'alice' })).body).toEqual({
        Team_Name: 'LEGAL',
        Username: 'alice',
        Status: 'User added',
      });
      expect(await members('LEGAL')).toContain('alice');
      expect((await teams({ Team_Name: 'LEGAL', Method: 'REMOVE_USER', Username: 'alice' })).body.Status).toBe(
        'User removed',
      );
      expect(await members('LEGAL')).not.toContain('alice');
    });

    it('rejects adding a member twice, removing a non-member, and unknown users or teams (v1.0.2)', async () => {
      expectError(await teams({ Team_Name: 'LEGAL', Method: 'ADD_USER', Username: 'carol' }), 'USER_EXISTS');
      expectError(await teams({ Team_Name: 'LEGAL', Method: 'REMOVE_USER', Username: 'alice' }), 'USER_DNE');
      expectError(await teams({ Team_Name: 'LEGAL', Method: 'ADD_USER', Username: 'mallory' }), 'USER_DNE');
      expectError(await teams({ Team_Name: 'GHOST', Method: 'ADD_USER', Username: 'alice' }), 'TEAM_DNE');
    });

    it('also takes DELETE for REMOVE', async () => {
      await teams({ Team_Name: 'Red Team', Method: 'NEW' });
      expect((await teams({ Team_Name: 'Red Team', Method: 'DELETE' })).body.Status).toBe('Removed');
    });

    it('lets tickets and the notifier use only existing teams', async () => {
      await teams({ Team_Name: 'Red Team', Method: 'NEW' });
      await newIncident();
      expect((await newTicket(undefined, { Team_list: ['Red Team'] })).status).toBe(200);
      expectError(await newTicket(undefined, { Team_list: ['Blue Team'] }), 'INVALID_DATA');
      expectError(
        await post('/notifier', { Team_Names: ['Blue Team'], Method: 'NOTIFY', Ticket_Number: `${ID}_1` }),
        'INVALID_DATA',
      );
    });

    it('keeps a team that tickets use', async () => {
      await teams({ Team_Name: 'Red Team', Method: 'NEW' });
      await newIncident();
      await newTicket(undefined, { Team_list: ['Red Team'] });
      expectError(await teams({ Team_Name: 'Red Team', Method: 'REMOVE' }), 'INVALID_DATA');
      expect(await names()).toContain('Red Team');
    });
  });

  describe('/users', () => {
    const users = (body: Record<string, unknown>) => post('/users', body);

    it('starts with the default users', async () => {
      const list = (await users({ Method: 'LIST' })).body.Users.map((u: { Username: string }) => u.Username);
      expect(list.sort()).toEqual(['alice', 'bob', 'carol', 'core-gateway', 'dana']);
    });

    it('creates, edits, fetches and removes a user', async () => {
      expect(
        (
          await users({
            Username: 'erin',
            Method: 'NEW',
            Auth_Hash: 'hash-1',
            Contact: 'erin@example.com',
            Display_Name: 'Erin',
            Contact_Channel: 'email',
          })
        ).body,
      ).toEqual({
        Username: 'erin',
        Display_Name: 'Erin',
        Contact: 'erin@example.com',
        Contact_Channel: 'email',
        Teams: [],
        Status: 'Created',
      });
      await post('/teams', { Team_Name: 'CYBER2', Method: 'ADD_USER', Username: 'erin' });
      expect(
        (await users({ Username: 'erin', Method: 'EDIT', Contact: 'e@example.com', Auth_Hash: 'hash-2' })).body,
      ).toMatchObject({ Contact: 'e@example.com', Teams: ['CYBER2'], Status: 'Edited' });
      expect((await users({ Username: 'erin', Method: 'GET' })).body.Status).toBe('User Received');
      expect((await users({ Username: 'erin', Method: 'REMOVE' })).body).toEqual({
        Username: 'erin',
        Status: 'Removed',
      });
      expectError(await users({ Username: 'erin', Method: 'GET' }), 'USER_DNE');
      expect((await post('/teams', { Team_Name: 'CYBER2', Method: 'GET' })).body.Members).not.toContain('erin');
    });

    it('never returns the credential, and takes DELETE for REMOVE', async () => {
      const created = await users({ Username: 'frank', Method: 'NEW', Auth_Hash: 'secret' });
      expect(JSON.stringify(created.body)).not.toMatch(/secret|scrypt|Auth_Hash/);
      expect((await users({ Username: 'frank', Method: 'DELETE' })).body.Status).toBe('Removed');
    });

    it('rejects duplicates, reserved names and bad input', async () => {
      expectError(await users({ Username: 'alice', Method: 'NEW', Auth_Hash: 'h' }), 'USER_EXISTS');
      expectError(await users({ Username: 'erin', Method: 'NEW' }), 'INVALID_DATA'); // Auth_Hash is required
      expectError(await users({ Username: 'Unknown', Method: 'NEW', Auth_Hash: 'h' }), 'INVALID_DATA');
      expectError(await users({ Username: 'notification-service', Method: 'NEW', Auth_Hash: 'h' }), 'INVALID_DATA');
      expectError(await users({ Username: '', Method: 'NEW', Auth_Hash: 'h' }), 'INVALID_DATA');
      expectError(await users({ Username: 'x', Method: 'NEW', Auth_Hash: 'h', Contact: 5 }), 'INVALID_DATA');
      expectError(await users({ Username: 'ghost', Method: 'EDIT' }), 'USER_DNE');
    });
  });

  describe('/test/setup and /test/report (cross-team tester)', () => {
    const run = (n: string) => `run-${Date.now()}-${n}`;
    const as = (id: string) => ({ 'x-session-id': id });
    const setup = (id: string) => post('/test/setup', { session_id: id, setup: {} });
    const report = async (id?: string) => {
      const res = await fetch(`${API}/test/report${id === undefined ? '' : `?session_id=${encodeURIComponent(id)}`}`);
      return { status: res.status, body: await res.json() };
    };

    it('gives each session its own data, apart from the real data', async () => {
      await newIncident();
      await post('/dependencies', { dp_name: 'okta', method: 'NEW' });
      const a = run('a');
      const b = run('b');
      expect(await setup(a)).toEqual({ status: 201, body: { session_id: a } });
      expect((await setup(b)).status).toBe(201);

      expectError(await getIncident(ID, as(a)), 'UUID_DNE');
      expect((await post('/dependencies', { dp_name: 'okta', method: 'MATCH' }, as(a))).body.status).toBe(
        'Does not Exist',
      );
      expect((await newIncident(undefined, {}, as(a))).status).toBe(200);
      expect((await newIncident(undefined, {}, as(b))).status).toBe(200);
      expect((await newTicket(undefined, { Team_list: ['CYBER2'] }, as(a))).body.Ticket_ID).toBe(`${ID}_1_1`);
      expect((await post('/reset', { method: 'RESET' }, as(b))).status).toBe(200);
      expectError(await getIncident(ID, as(b)), 'UUID_DNE');
      expect((await getIncident(ID, as(a))).status).toBe(200);

      // the real data is untouched
      expect((await getIncident()).status).toBe(200);
      expect((await post('/dependencies', { dp_name: 'okta', method: 'MATCH' })).body.status).toBe('Exists');
      await report(a);
      await report(b);
    });

    it('ends the session at /test/report, with its coverage and timings', async () => {
      const id = run('c');
      await setup(id);
      await newIncident(undefined, {}, as(id));
      await getIncident(ID, as(id));
      const r = await report(id);
      expect(r.status).toBe(200);
      expect(r.body).toMatchObject({
        session_id: id,
        coverage: { code: { basis: expect.any(String) } },
        metrics: {
          requests: expect.arrayContaining([
            expect.objectContaining({ operation: '/incidents NEW', count: 1, errors: 0 }),
            expect.objectContaining({ operation: '/incidents GET', count: 1 }),
          ]),
        },
      });
      const { covered, total } = r.body.coverage.code;
      expect(covered).toBeGreaterThan(0);
      expect(total).toBeGreaterThanOrEqual(covered);

      expect(await report(id)).toEqual(r); // stored
      expectError(await getIncident(ID, as(id)), 'INVALID_DATA'); // ended
      expect((await setup(id)).status).toBe(409); // session IDs are single use
    });

    it('rejects a session ID that is already active', async () => {
      const id = run('d');
      expect((await setup(id)).status).toBe(201);
      expect(await setup(id)).toEqual({ status: 409, body: { message: expect.any(String), source: 'system' } });
      await report(id);
    });

    it('rejects invalid requests in the tester error format', async () => {
      for (const body of [{}, { session_id: '' }, { session_id: 5 }, { session_id: 'x', setup: [] }]) {
        expect(await post('/test/setup', body)).toEqual({
          status: 400,
          body: { message: expect.any(String), source: 'system' },
        });
      }
      expect((await report()).status).toBe(400);
      expect((await report('never-set-up')).status).toBe(404);
      expectError(await getIncident(ID, as('never-set-up')), 'INVALID_DATA');
    });
  });

  describe.skipIf(!INGEST_TOKEN)('/ingest (ingestion worker, not in the pod contract)', () => {
    const auth = { authorization: `Bearer ${INGEST_TOKEN}`, 'content-type': 'application/json' };
    const report = {
      company_id: 'default',
      source: 'cisa_kev',
      external_id: 'CVE-2026-0001',
      title: 'Test vuln',
      summary: 'Summary.',
      source_url: 'https://example.com/CVE-2026-0001',
      published_at: TS,
      detected_at: TS,
      priority_hint: 'high',
      matched_dependencies: [
        { dependency_id: 'Acme:Widget', vendor: 'Acme', product: 'Widget', confidence: 'high', reason: 'test' },
      ],
    };

    it('rejects a missing token', async () => {
      expect((await fetch(`${API}/ingest/dependencies`)).status).toBe(401);
    });

    it('serves dependencies split into vendor and product', async () => {
      await post('/dependencies', { dp_name: 'Acme:Widget Server', method: 'NEW' });
      await post('/dependencies', { dp_name: 'BeyondTrust Remote Support', method: 'NEW' });
      const deps = await (await fetch(`${API}/ingest/dependencies`, { headers: auth })).json();
      expect(deps).toEqual([
        expect.objectContaining({ id: 'Acme:Widget Server', vendor: 'Acme', product: 'Widget Server' }),
        expect.objectContaining({ id: 'BeyondTrust Remote Support', vendor: 'BeyondTrust', product: 'Remote Support' }),
      ]);
    });

    it('creates an incident once as the worker, then returns the stored one', async () => {
      const send = () =>
        fetch(`${API}/ingest/incidents`, { method: 'POST', headers: auth, body: JSON.stringify(report) });
      const first = await send();
      expect(first.status).toBe(201);
      const created = await first.json();
      const again = await send();
      expect(again.status).toBe(200);
      expect((await again.json()).id).toBe(created.id);

      expect((await getIncident(created.id)).body).toMatchObject({
        Dependency: 'Acme:Widget',
        Materiality: 'UNDECIDED',
      });
      const log = (await post('/logs', { Incident_ID: created.id, Timestamp: TS })).body.Audit_Log;
      expect(log[0]).toMatchObject({ Event: 'INCIDENT_CREATED', Actor: 'ingestion-worker' });
    });

    describe('a repeat report', () => {
      const widget = report.matched_dependencies[0];
      const gadget = { ...widget, dependency_id: 'Acme:Gadget', product: 'Gadget', confidence: 'low' };
      const send = async (body: object) => {
        const res = await fetch(`${API}/ingest/incidents`, {
          method: 'POST',
          headers: auth,
          body: JSON.stringify(body),
        });
        return { status: res.status, body: await res.json() };
      };
      const events = async (id: string) =>
        (await post('/logs', { Incident_ID: id, Timestamp: TS })).body.Audit_Log as {
          Event: string;
          Actor: string;
          Details: { matches?: { dependency_id: string }[] };
        }[];

      it('adds newly matched dependencies, once, and keeps the rest of the incident', async () => {
        const created = (await send(report)).body;
        const changed = { ...report, title: 'Changed title', matched_dependencies: [gadget] };
        const updated = await send(changed);
        expect(updated.status).toBe(200);
        expect(updated.body.id).toBe(created.id);
        expect(updated.body.title).toBe('Test vuln');
        expect(updated.body.matched_dependencies).toEqual([widget, gadget]); // keeps what this report left out
        expect((await send(changed)).body.matched_dependencies).toEqual([widget, gadget]);

        expect((await getIncident(created.id)).body.Dependency).toBe('Acme:Widget');
        const added = (await events(created.id)).filter((e) => e.Event === 'INCIDENT_MATCHES_ADDED');
        expect(added).toHaveLength(1);
        expect(added[0].Actor).toBe('ingestion-worker');
        expect(added[0].Details.matches?.map((m) => m.dependency_id)).toEqual(['Acme:Gadget']);
      });

      it('logs nothing when no dependency is new', async () => {
        const { id } = (await send(report)).body;
        await send(report);
        expect((await events(id)).map((e) => e.Event)).not.toContain('INCIDENT_MATCHES_ADDED');
      });

      it('notifies for a normal report, and not for a backfill', async () => {
        const sent = async (id: string) => (await events(id)).filter((e) => e.Event === 'NOTIFICATION_SENT').length;
        const { id } = (await send(report)).body;
        const before = await sent(id);
        await send({ ...report, backfill: true, matched_dependencies: [gadget] });
        expect(await sent(id)).toBe(before);
        await send({ ...report, matched_dependencies: [{ ...gadget, dependency_id: 'Acme:Third' }] });
        expect(await sent(id)).toBe(before + (before ? 1 : 0)); // only with a notifier configured

        const old = await send({ ...report, external_id: 'CVE-2020-0001', backfill: true });
        expect(old.status).toBe(201);
        expect(old.body.backfill).toBe(true);
        expect(await sent(old.body.id)).toBe(0);
      });

      it('rejects malformed matches', async () => {
        for (const matched_dependencies of ['x', [{}], [null]]) {
          expectError(await send({ ...report, matched_dependencies }), 'INVALID_DATA');
        }
      });
    });

    describe('notification results', () => {
      const notifAuth = {
        authorization: `Bearer ${process.env.NOTIF_CORE_API_TOKEN}`,
        'content-type': 'application/json',
      };

      it.skipIf(!process.env.NOTIF_CORE_API_TOKEN)('finds the incident from an update notice ID', async () => {
        const created = await fetch(`${API}/ingest/incidents`, {
          method: 'POST',
          headers: auth,
          body: JSON.stringify(report),
        });
        const { id } = await created.json();
        const results = (path: string) =>
          fetch(`${API}/notif/notifications/${path}/results`, {
            method: 'POST',
            headers: notifAuth,
            body: JSON.stringify({ results: [] }),
          });
        expect((await results(`${id}:deps:abc`)).status).toBe(200);
        expect((await results('000000000001:deps:abc')).status).toBe(404);
      });
    });
  });
});
