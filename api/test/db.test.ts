// Database tests: MySqlDb against a real MySQL. WIPES that database.
// Runs only when DB_USER is set, e.g. against `docker compose up db`:
//   DB_HOST=127.0.0.1 DB_USER=... DB_PASSWORD=... npm run test:db
import mysql from 'mysql2/promise';
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
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
