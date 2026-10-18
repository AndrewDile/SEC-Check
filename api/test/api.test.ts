// HTTP tests for the pod contract (v1.0.0) against any deployed Core API. WIPES its data via /reset.
// Runs only when API_URL is set, e.g.:
//   API_URL=http://localhost:3001 npm run test:api
// The /ingest tests are ours (not in the pod contract) and also need INGEST_CORE_API_TOKEN.
import { beforeEach, describe, expect, it } from 'vitest';

const API = process.env.API_URL;
const INGEST_TOKEN = process.env.INGEST_CORE_API_TOKEN;
const TS = '2026-09-25T20:00:00Z';

async function post(path: string, body: unknown) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await res.json() };
}

const newIncident = (id = '102356304331', extra = {}) =>
  post('/incidents', {
    Incident_ID: id,
    Method: 'NEW',
    Timestamp: TS,
    Description: 'Critical API gateway timeout.',
    ...extra,
  });
const newTicket = (id = '102356304331', extra = {}) =>
  post('/tickets', { Incident_ID: id, Method: 'NEW', Timestamp: TS, Description: 'Initial triage.', ...extra });

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
        Incident_ID: '102356304331',
        Status: 'Created',
        Materiality: 'MATERIAL',
        Severity: 'HIGH',
        Urgency: 'URGENT',
      });

      const got = await post('/incidents', {
        Incident_ID: '102356304331',
        Method: 'GET',
        Timestamp: TS,
        Description: '',
      });
      expect(got.body).toMatchObject({
        Status: 'Data Fetched',
        Description: 'Critical API gateway timeout.',
        Dependency: 'auth-service-v2',
      });

      const edited = await post('/incidents', {
        Incident_ID: '102356304331',
        Method: 'EDIT',
        Timestamp: TS,
        Description: 'Updated.',
        Materiality: 'IMMATERIAL',
      });
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
      expectError(
        await post('/incidents', { Incident_ID: '000000000001', Method: 'GET', Timestamp: TS, Description: '' }),
        'UUID_DNE',
      );
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
        Incident_ID: '102356304331',
        Ticket_ID: '102356304331_1_1',
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
        Incident_ID: '102356304331',
        Method: 'EDIT',
        Timestamp: TS,
        Ticket_number: '102356304331_1',
        Description: 'Second look.',
      });
      expect(edited.body).toMatchObject({ Ticket_ID: '102356304331_1_2', Status: 'Edited' });

      const latest = await post('/tickets', {
        Incident_ID: '102356304331',
        Method: 'GET',
        Timestamp: TS,
        Ticket_number: '102356304331_1',
      });
      expect(latest.body).toMatchObject({
        Ticket_ID: '102356304331_1_2',
        Status: 'Displayed',
        Ticket_Description: 'Second look.',
      });

      const first = await post('/tickets', {
        Incident_ID: '102356304331',
        Method: 'GET',
        Timestamp: TS,
        Ticket_number: '102356304331_1_1',
      });
      expect(first.body.Ticket_Description).toBe('Initial triage.');
    });

    it('rejects unknown incidents and tickets', async () => {
      expectError(await newTicket('000000000001'), 'UUID_DNE');
      expectError(
        await post('/tickets', {
          Incident_ID: '102356304331',
          Method: 'GET',
          Timestamp: TS,
          Ticket_number: '102356304331_9',
        }),
        'UUID_DNE',
      );
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
        Ticket_Number: '102356304331_1',
      });
      expect(notified.body).toEqual({ UUID: 102356304331, Ticket_Number: '102356304331_1', Status: 'Notified team' });

      const claimed = await post('/notifier', {
        Team_Names: ['CYBER1'],
        Method: 'CLAIM',
        Ticket_Number: '102356304331_1',
      });
      expect(claimed.body.Status).toBe('Claimed ticket');
      expectError(
        await post('/notifier', { Team_Names: ['CYBER2'], Method: 'CLAIM', Ticket_Number: '102356304331_1' }),
        'INVALID_DATA',
      );

      const ticket = await post('/tickets', {
        Incident_ID: '102356304331',
        Method: 'GET',
        Timestamp: TS,
        Ticket_number: '102356304331_1',
      });
      expect(ticket.body.Ticket_Claim).toBe('CLAIMED');
    });

    it('rejects empty or unknown teams', async () => {
      expectError(
        await post('/notifier', { Team_Names: [], Method: 'CLAIM', Ticket_Number: '102356304331_1' }),
        'INVALID_DATA',
      );
      expectError(
        await post('/notifier', { Team_Names: ['NOPE'], Method: 'NOTIFY', Ticket_Number: '102356304331_1' }),
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
        Incident_ID: '102356304331',
        Method: 'EDIT',
        Timestamp: TS,
        Ticket_number: '102356304331_1',
        Description: 'Edit.',
      });
      const r = await post('/logs', { Incident_ID: '102356304331', Timestamp: TS });
      expect(r.body).toMatchObject({
        Incident_ID: '102356304331',
        Materiality_type: 'MATERIAL',
        Status: 'Log Retrieved',
        Ticket_ID_List: ['102356304331_1_1', '102356304331_2_1', '102356304331_1_2'],
      });
    });

    it('rejects a future timestamp and unknown incidents', async () => {
      await newIncident();
      expectError(
        await post('/logs', { Incident_ID: '102356304331', Timestamp: '2999-09-25T20:30:00Z' }),
        'INVALID_DATA',
      );
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

  describe('/test/setup and /test/report (cross-team tester)', () => {
    const report = async (id?: string) => {
      const res = await fetch(`${API}/test/report${id === undefined ? '' : `?session_id=${encodeURIComponent(id)}`}`);
      return { status: res.status, body: await res.json() };
    };

    it('wipes the database and makes the session active', async () => {
      await post('/dependencies', { dp_name: 'okta', method: 'NEW' });
      const id = `run-${Date.now()}-a`;
      expect(await post('/test/setup', { session_id: id, setup: { teams: ['LEGAL', 'CYBER1', 'CYBER2'] } })).toEqual({
        status: 201,
        body: { session_id: id },
      });
      expect((await post('/dependencies', { dp_name: 'okta', method: 'MATCH' })).body.status).toBe('Does not Exist');
      // default teams are back after the wipe
      expect((await newIncident()).status).toBe(200);
      expect((await newTicket(undefined, { Team_list: ['CYBER2'] })).status).toBe(200);

      const r = await report(id);
      expect(r.status).toBe(200);
      expect(r.body).toEqual({
        session_id: id,
        coverage: { code: { covered: null, total: null, basis: expect.any(String) } },
      });
    });

    it('allows one session at a time', async () => {
      const first = `run-${Date.now()}-b`,
        second = `run-${Date.now()}-c`;
      expect((await post('/test/setup', { session_id: first })).status).toBe(201);
      expect(await post('/test/setup', { session_id: first })).toEqual({
        status: 409,
        body: { message: expect.any(String), source: 'system' },
      });
      expect((await post('/test/setup', { session_id: second })).status).toBe(201);
      expect((await report(first)).status).toBe(404); // replaced by the new session
      expect((await report(second)).status).toBe(200);
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

    it('creates an incident once, then returns the stored one', async () => {
      const send = () =>
        fetch(`${API}/ingest/incidents`, { method: 'POST', headers: auth, body: JSON.stringify(report) });
      const first = await send();
      expect(first.status).toBe(201);
      const created = await first.json();
      const again = await send();
      expect(again.status).toBe(200);
      expect((await again.json()).id).toBe(created.id);

      const got = await post('/incidents', { Incident_ID: created.id, Method: 'GET', Timestamp: TS, Description: '' });
      expect(got.body).toMatchObject({ Dependency: 'Acme:Widget', Materiality: 'UNDECIDED' });
    });
  });
});
