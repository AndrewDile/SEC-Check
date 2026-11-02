// Database tests: MySqlDb against a real MySQL. WIPES that database.
// Runs only when DB_USER is set, e.g. against `docker compose up db`:
//   DB_HOST=127.0.0.1 DB_USER=... DB_PASSWORD=... npm run test:db
import mysql from 'mysql2/promise';
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import { addBusinessDays, newYorkDate } from '../src/calendar.js';
import { runIn } from '../src/context.js';
import { DbError } from '../src/db/api.js';
import { MySqlDb } from '../src/db/mysql.js';

const enabled = Boolean(process.env.DB_USER);
const at = new Date('2026-09-25T20:00:00Z');

async function dbError(p: Promise<unknown>) {
  const e = await p.then(
    () => undefined,
    (err) => err,
  );
  expect(e).toBeInstanceOf(DbError);
  return (e as DbError).type;
}

describe.skipIf(!enabled)('MySqlDb', () => {
  const db = MySqlDb.fromEnv();
  const newIncident = (incidentId = '100', extra = {}) =>
    db.createIncident({ incidentId, description: 'Test incident', reportedAt: at, ...extra });

  beforeEach(() => db.reset());
  afterAll(() => db.close());

  describe('addIncidentMatches', () => {
    const match = (dependency_id: string) => ({ dependency_id, confidence: 'low' });
    const reported = () =>
      newIncident('100', {
        source: 'cisa_kev',
        externalId: 'CVE-1',
        ingest: { id: '100', title: 'T', matched_dependencies: [match('a')] },
      });

    it('adds only what is new, and stores it', async () => {
      await reported();
      const { ingest, added } = await db.addIncidentMatches('100', [match('a'), match('b')]);
      expect(added).toEqual(['b']);
      expect(ingest).toEqual({ id: '100', title: 'T', matched_dependencies: [match('a'), match('b')] });
      expect((await db.getIncident('100')).ingest).toEqual(ingest);
    });

    it('changes nothing when no match is new', async () => {
      await reported();
      expect((await db.addIncidentMatches('100', [match('a')])).added).toEqual([]);
      expect((await db.addIncidentMatches('100', [])).added).toEqual([]);
    });

    it('adds each match once when reports race', async () => {
      await reported();
      const results = await Promise.all([1, 2, 3].map(() => db.addIncidentMatches('100', [match('b')])));
      expect(results.flatMap((r) => r.added)).toEqual(['b']);
    });

    it('rejects an unknown incident', async () => {
      expect(await dbError(db.addIncidentMatches('404', [match('a')]))).toBe('UUID_DNE');
    });
  });

  describe('incidents', () => {
    it('creates with UNDECIDED defaults and reads back', async () => {
      await newIncident('100', { dependencyName: 'acme' });
      expect(await db.getIncident('100')).toMatchObject({
        incidentId: '100',
        description: 'Test incident',
        dependencyName: 'acme',
        materiality: 'UNDECIDED',
        severity: 'UNDECIDED',
        urgency: 'UNDECIDED',
        reportedAt: at,
      });
    });

    it('rejects a duplicate ID and unknown IDs', async () => {
      await newIncident();
      expect(await dbError(newIncident())).toBe('UUID_EXISTS');
      expect(await dbError(db.getIncident('999'))).toBe('UUID_DNE');
      expect(await dbError(db.editIncident('999', { description: 'x' }))).toBe('UUID_DNE');
    });

    it('edits only the given fields, and "" clears the dependency', async () => {
      await newIncident('100', { dependencyName: 'acme' });
      const edited = await db.editIncident('100', { materiality: 'MATERIAL', dependencyName: '' });
      expect(edited).toMatchObject({ materiality: 'MATERIAL', severity: 'UNDECIDED', description: 'Test incident' });
      expect(edited.dependencyName).toBeUndefined();
    });

    it('finds worker incidents by (source, external_id), which is unique', async () => {
      await newIncident('100', { source: 'cisa_kev', externalId: 'CVE-1', ingest: { id: '100', title: 't' } });
      expect(await db.findIncidentBySource('cisa_kev', 'CVE-1')).toMatchObject({
        incidentId: '100',
        ingest: { id: '100', title: 't' },
      });
      expect(await db.findIncidentBySource('cisa_kev', 'CVE-2')).toBeUndefined();
      expect(await dbError(newIncident('101', { source: 'cisa_kev', externalId: 'CVE-1' }))).toBe('UUID_EXISTS');
    });

    it('lists incidents', async () => {
      await newIncident('100');
      await newIncident('101');
      expect((await db.listIncidents()).map((i) => i.incidentId)).toEqual(['100', '101']);
    });
  });

  describe('tickets', () => {
    beforeEach(() => newIncident());

    it('numbers tickets per incident and starts at version 1', async () => {
      const t1 = await db.createTicket('100', { description: 'a', teams: ['CYBER1'], reportedAt: at });
      const t2 = await db.createTicket('100', { description: 'b', reportedAt: at });
      expect(t1).toMatchObject({
        ticketId: '100_1_1',
        ticketNumber: 1,
        version: 1,
        teams: ['CYBER1'],
        severity: 'UNDECIDED',
      });
      expect(t2.ticketId).toBe('100_2_1');
    });

    it('edits by adding a version, keeping fields that were not given', async () => {
      await db.createTicket('100', { description: 'a', severity: 'HIGH', teams: ['LEGAL'], reportedAt: at });
      const v2 = await db.editTicket('100', 1, { description: 'b' });
      expect(v2).toMatchObject({ ticketId: '100_1_2', description: 'b', severity: 'HIGH', teams: ['LEGAL'] });
      expect((await db.getTicket('100', 1)).version).toBe(2);
      expect((await db.getTicket('100', 1, 1)).description).toBe('a');
      expect(await db.listTicketIds('100')).toEqual(['100_1_1', '100_1_2']);
    });

    it('gives concurrent new tickets distinct numbers', async () => {
      const tickets = await Promise.all(
        Array.from({ length: 10 }, () => db.createTicket('100', { description: 'a', reportedAt: at })),
      );
      expect(tickets.map((t) => t.ticketNumber).sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    });

    it('rejects unknown incidents, tickets, versions and teams', async () => {
      await db.createTicket('100', { description: 'a', reportedAt: at });
      expect(await dbError(db.createTicket('999', { description: 'a', reportedAt: at }))).toBe('UUID_DNE');
      expect(await dbError(db.getTicket('100', 9))).toBe('UUID_DNE');
      expect(await dbError(db.getTicket('100', 1, 9))).toBe('UUID_DNE');
      expect(await dbError(db.createTicket('100', { description: 'a', teams: ['NOPE'], reportedAt: at }))).toBe(
        'INVALID_DATA',
      );
    });

    it('lets one team claim a ticket, across all its versions', async () => {
      await db.createTicket('100', { description: 'a', reportedAt: at });
      await db.claimTicket('100', 1, 'CYBER1');
      await db.claimTicket('100', 1, 'CYBER1'); // same team again is fine
      expect(await dbError(db.claimTicket('100', 1, 'CYBER2'))).toBe('INVALID_DATA');
      await db.editTicket('100', 1, { description: 'b' });
      expect((await db.getTicket('100', 1)).claimedBy).toBe('CYBER1');
      expect((await db.listTickets()).map((t) => t.claimedBy)).toEqual(['CYBER1']);
    });

    it('lets only one of two teams claiming at once win', async () => {
      await db.createTicket('100', { description: 'a', reportedAt: at });
      const results = await Promise.allSettled([
        db.claimTicket('100', 1, 'CYBER1'),
        db.claimTicket('100', 1, 'CYBER2'),
      ]);
      expect(results.map((r) => r.status).sort()).toEqual(['fulfilled', 'rejected']);
    });

    it('gives concurrent edits distinct versions', async () => {
      await db.createTicket('100', { description: 'a', reportedAt: at });
      await Promise.all(Array.from({ length: 5 }, (_, i) => db.editTicket('100', 1, { description: `v${i}` })));
      expect((await db.getTicket('100', 1)).version).toBe(6);
    });

    it('records notifications for existing tickets only', async () => {
      await db.createTicket('100', { description: 'a', reportedAt: at });
      await db.notifyTeams('100', 1, ['LEGAL', 'CYBER1']);
      expect(await dbError(db.notifyTeams('100', 9, ['LEGAL']))).toBe('UUID_DNE');
      expect((await db.getAuditLog('100')).map((e) => e.eventType)).toContain('TEAMS_NOTIFIED');
    });
  });

  describe('dependencies', () => {
    it('adds, matches, lists and removes', async () => {
      await db.addDependency('Acme:Widget');
      expect(await dbError(db.addDependency('Acme:Widget'))).toBe('DP_EXISTS');
      expect(await db.hasDependency('Acme:Widget')).toBe(true);
      expect(await db.listDependencies()).toEqual(['Acme:Widget']);
      await db.removeDependency('Acme:Widget');
      expect(await db.hasDependency('Acme:Widget')).toBe(false);
      expect(await dbError(db.removeDependency('Acme:Widget'))).toBe('DP_DNE');
    });
  });

  describe('audit log', () => {
    it('logs writes and reads per incident, in order', async () => {
      await newIncident();
      await db.getIncident('100');
      await db.createTicket('100', { description: 'a', reportedAt: at });
      await db.logEvent('100', 'CUSTOM', { x: 1 });
      const log = await db.getAuditLog('100');
      expect(log.map((e) => e.eventType)).toEqual(['INCIDENT_CREATED', 'INCIDENT_READ', 'TICKET_CREATED', 'CUSTOM']);
      expect(log.at(-1)!.payload).toEqual({ x: 1 });
    });

    it('keeps a valid hash chain under concurrent writes', async () => {
      await newIncident();
      await Promise.all(Array.from({ length: 20 }, (_, i) => db.logEvent('100', 'CONCURRENT', { i })));
      const log = await db.getAuditLog('100');
      expect(log.filter((e) => e.eventType === 'CONCURRENT')).toHaveLength(20);
      expect(new Set(log.map((e) => e.seq)).size).toBe(log.length);
      expect(await db.verifyAuditChain()).toEqual({ ok: true });
    });

    it('refuses UPDATE and DELETE on append-only tables (REQ-02)', async () => {
      await newIncident();
      await db.createTicket('100', { description: 'a', reportedAt: at });
      const raw = await mysql.createConnection({
        host: process.env.DB_HOST ?? 'localhost',
        port: Number(process.env.DB_PORT ?? 3306),
        user: process.env.DB_USER,
        password: process.env.DB_PASSWORD,
        database: process.env.DB_NAME ?? 'seccheck',
      });
      try {
        await expect(raw.query("UPDATE audit_log SET event_type = 'X'")).rejects.toThrow(/append-only/);
        await expect(raw.query('DELETE FROM audit_log')).rejects.toThrow(/append-only/);
        await expect(raw.query("UPDATE ticket_versions SET description = 'X'")).rejects.toThrow(/append-only/);
      } finally {
        await raw.end();
      }
    });
  });

  describe('materiality and the filing deadline', () => {
    beforeEach(() => newIncident());

    it('sets the deadline at the first MATERIAL determination and keeps it', async () => {
      const material = await db.editIncident('100', { materiality: 'MATERIAL' });
      expect(material.filingDeadline).toBe(
        addBusinessDays(
          newYorkDate(material.materialAt!),
          4,
          new Set(['2026-11-11', '2026-11-26', '2026-12-25', '2027-01-01', '2027-01-18']),
        ),
      );
      await db.editIncident('100', { materiality: 'IMMATERIAL' }, 'Contained.');
      const again = await db.editIncident('100', { materiality: 'MATERIAL' });
      expect(again).toMatchObject({ filingDeadline: material.filingDeadline, materialAt: material.materialAt });
    });

    it('needs a note to reverse MATERIAL, and audits the reversal', async () => {
      await db.editIncident('100', { materiality: 'MATERIAL' });
      expect(await dbError(db.editIncident('100', { materiality: 'UNDECIDED' }))).toBe('INVALID_DATA');
      expect(await dbError(db.editIncident('100', { materiality: 'IMMATERIAL' }, '  '))).toBe('INVALID_DATA');
      await db.editIncident('100', { materiality: 'IMMATERIAL' }, 'Contained.');
      expect((await db.getAuditLog('100')).at(-1)).toMatchObject({
        eventType: 'MATERIALITY_REVERSED',
        payload: { before: { materiality: 'MATERIAL' }, after: { materiality: 'IMMATERIAL' }, note: 'Contained.' },
      });
    });
  });

  describe('users and team members', () => {
    it('restores the default users and members on reset', async () => {
      expect((await db.listUsers()).map((u) => u.username).sort()).toEqual([
        'alice',
        'bob',
        'carol',
        'core-gateway',
        'dana',
      ]);
      expect((await db.getUser('dana')).teams).toEqual(['CYBER1', 'LEGAL']);
    });

    it('adds members, and notifies them at their contact', async () => {
      await db.createUser({ username: 'erin', contactChannel: 'email', contactAddress: 'erin@example.com' });
      await db.createTeam('EMPTY');
      await db.addMember('CYBER2', 'erin');
      expect(await dbError(db.addMember('CYBER2', 'erin'))).toBe('USER_EXISTS');
      expect((await db.getTeam('CYBER2')).members).toEqual(['bob', 'core-gateway', 'erin']);
      const contacts = await db.listContacts();
      expect(contacts).toContainEqual({
        team: 'CYBER2',
        username: 'erin',
        channel: 'email',
        address: 'erin@example.com',
      });
      expect(contacts).toContainEqual({ team: 'CYBER2', username: 'bob', channel: 'log', address: 'bob' });
      expect(contacts).toContainEqual({ team: 'EMPTY', channel: 'log', address: 'EMPTY' });
      expect(await dbError(db.addMember('CYBER2', 'mallory'))).toBe('USER_DNE');
      expect(await dbError(db.addMember('GHOST', 'erin'))).toBe('TEAM_DNE');
      await db.removeUser('erin');
      expect((await db.getTeam('CYBER2')).members).not.toContain('erin');
    });
  });

  describe('scopes and test sessions', () => {
    it('keeps each session apart from the real data, records the actor, and purges it once ended', async () => {
      await newIncident('100');
      const scope = await db.createSession(`db-test-${Date.now()}`);
      await runIn({ scope, actor: 'alice' }, async () => {
        expect(await db.listIncidents()).toEqual([]);
        await newIncident('100');
        expect((await db.getAuditLog('100')).map((e) => e.actor)).toEqual(['alice']);
        expect(await db.verifyAuditChain()).toEqual({ ok: true });
      });
      expect((await db.getAuditLog('100')).map((e) => e.actor)).toEqual(['Unknown']);

      await db.endSession(scope, { done: true });
      expect(await db.purgeEndedSessions(new Date(Date.now() + 1000))).toBeGreaterThanOrEqual(1);
      await runIn({ scope, actor: 'alice' }, async () => expect(await db.listIncidents()).toEqual([]));
      expect((await db.listIncidents()).map((i) => i.incidentId)).toEqual(['100']);
    });

    it('rejects a session ID that was already used', async () => {
      const id = `db-test-${Date.now()}-again`;
      await db.createSession(id);
      expect(await dbError(db.createSession(id))).toBe('UUID_EXISTS');
    });
  });

  describe('reset', () => {
    it('wipes everything and restores the default teams', async () => {
      await newIncident();
      await db.addDependency('Acme');
      await db.createTeam('EXTRA');
      await db.reset();
      expect(await db.listIncidents()).toEqual([]);
      expect(await db.listDependencies()).toEqual([]);
      expect((await db.listTeams()).map((t) => t.name).sort()).toEqual(['CYBER1', 'CYBER2', 'LEGAL']);
      expect(await db.verifyAuditChain()).toEqual({ ok: true });
    });
  });
});
