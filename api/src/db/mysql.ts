// MySQL implementation of the Database interface (schema: db/migrations/001_initial.sql).
import { createHash } from 'node:crypto';
import mysql, { Pool, PoolConnection, RowDataPacket } from 'mysql2/promise';
import { AuditEntry, Database, DbError, Incident, Severity, Ticket, Urgency } from './api.js';

const DEFAULT_TEAMS = ['LEGAL', 'CYBER1', 'CYBER2'];
const GENESIS = '0'.repeat(64);

type Conn = Pool | PoolConnection;

// hash = SHA-256(prev_hash + row)
function chainHash(prev: string, seq: number, occurredAt: Date, incidentId: string | null, eventType: string, payloadJson: string) {
  return createHash('sha256').update(prev + JSON.stringify([seq, occurredAt.toISOString(), incidentId, eventType, payloadJson])).digest('hex');
}

function toIncident(r: RowDataPacket): Incident {
  return {
    incidentId: r.incident_id,
    description: r.description,
    dependencyName: r.dependency_name ?? undefined,
    materiality: r.materiality,
    severity: r.severity,
    urgency: r.urgency,
    reportedAt: r.reported_at,
    source: r.source ?? undefined,
    externalId: r.external_id ?? undefined,
    ingest: r.ingest_json ?? undefined,
  };
}

export class MySqlDb implements Database {
  constructor(private pool: Pool) {}

  static fromEnv() {
    return new MySqlDb(mysql.createPool({
      host: process.env.DB_HOST ?? 'localhost',
      port: Number(process.env.DB_PORT ?? 3306),
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
      database: process.env.DB_NAME ?? 'seccheck',
      timezone: 'Z',
    }));
  }

  close() {
    return this.pool.end();
  }

  private async rows(c: Conn, sql: string, params: unknown[] = []) {
    const [r] = await c.query<RowDataPacket[]>(sql, params);
    return r;
  }

  // InnoDB can still deadlock on gap locks (e.g. two new tickets on one incident); MySQL says to retry.
  private async tx<T>(fn: (c: PoolConnection) => Promise<T>): Promise<T> {
    for (let attempt = 1; ; attempt++) {
      try {
        return await this.txOnce(fn);
      } catch (e) {
        if ((e as { code?: string }).code !== 'ER_LOCK_DEADLOCK' || attempt === 5) throw e;
        await new Promise(r => setTimeout(r, Math.random() * 20 * attempt));
      }
    }
  }

  private async txOnce<T>(fn: (c: PoolConnection) => Promise<T>): Promise<T> {
    const c = await this.pool.getConnection();
    try {
      await c.beginTransaction();
      const result = await fn(c);
      await c.commit();
      return result;
    } catch (e) {
      await c.rollback();
      const code = (e as { code?: string }).code;
      if (code === 'ER_NO_REFERENCED_ROW_2') throw new DbError('INVALID_DATA', 'Unknown team name.');
      if (code === 'ER_DATA_TOO_LONG' || code === 'WARN_DATA_TRUNCATED') throw new DbError('INVALID_DATA', 'A field is too long or has an invalid value.');
      throw e;
    } finally {
      c.release();
    }
  }

  private async audit(c: Conn, incidentId: string | undefined, eventType: string, payload: unknown) {
    const [head] = await this.rows(c, 'SELECT seq, hash FROM audit_head WHERE id = 1 FOR UPDATE');
    const seq = Number(head.seq) + 1;
    const prev = head.hash;
    const occurredAt = new Date();
    const payloadJson = JSON.stringify(payload ?? {});
    const hash = chainHash(prev, seq, occurredAt, incidentId ?? null, eventType, payloadJson);
    await c.query(
      'INSERT INTO audit_log (seq, occurred_at, incident_id, event_type, payload_json, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?)',
      [seq, occurredAt, incidentId ?? null, eventType, payloadJson, prev, hash],
    );
    await c.query('UPDATE audit_head SET seq = ?, hash = ? WHERE id = 1', [seq, hash]);
  }

  private async incident(c: Conn, incidentId: string): Promise<Incident> {
    const [r] = await this.rows(c, 'SELECT * FROM incidents WHERE incident_id = ?', [incidentId]);
    if (!r) throw new DbError('UUID_DNE', 'The specified Incident_ID does not exist.');
    return toIncident(r);
  }

  private async ticket(c: Conn, incidentId: string, ticketNumber: number, version?: number): Promise<Ticket> {
    await this.incident(c, incidentId);
    const [r] = version === undefined
      ? await this.rows(c, 'SELECT * FROM ticket_versions WHERE incident_id = ? AND ticket_number = ? ORDER BY version DESC LIMIT 1', [incidentId, ticketNumber])
      : await this.rows(c, 'SELECT * FROM ticket_versions WHERE incident_id = ? AND ticket_number = ? AND version = ?', [incidentId, ticketNumber, version]);
    if (!r) throw new DbError('UUID_DNE', 'The specified ticket does not exist.');
    const teams = await this.rows(c, 'SELECT team_name FROM ticket_version_teams WHERE incident_id = ? AND ticket_number = ? AND version = ?', [incidentId, ticketNumber, r.version]);
    const [claim] = await this.rows(c, 'SELECT team_name FROM ticket_claims WHERE incident_id = ? AND ticket_number = ? ORDER BY claim_id DESC LIMIT 1', [incidentId, ticketNumber]);
    return {
      ticketId: `${incidentId}_${ticketNumber}_${r.version}`,
      incidentId,
      ticketNumber,
      version: r.version,
      description: r.description,
      severity: r.severity,
      urgency: r.urgency,
      teams: teams.map(t => t.team_name),
      claimedBy: claim?.team_name,
      reportedAt: r.reported_at,
    };
  }

  private async insertVersion(c: Conn, t: Omit<Ticket, 'ticketId' | 'claimedBy'>) {
    await c.query(
      'INSERT INTO ticket_versions (incident_id, ticket_number, version, description, severity, urgency, reported_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
      [t.incidentId, t.ticketNumber, t.version, t.description, t.severity, t.urgency, t.reportedAt, new Date()],
    );
    for (const team of t.teams) {
      await c.query('INSERT INTO ticket_version_teams (incident_id, ticket_number, version, team_name) VALUES (?, ?, ?, ?)', [t.incidentId, t.ticketNumber, t.version, team]);
    }
  }

  // /incidents

  async createIncident(i: Omit<Incident, 'materiality' | 'severity' | 'urgency'> & Partial<Incident>) {
    const incident: Incident = { ...i, materiality: i.materiality ?? 'UNDECIDED', severity: i.severity ?? 'UNDECIDED', urgency: i.urgency ?? 'UNDECIDED' };
    const now = new Date();
    return this.tx(async c => {
      try {
        await c.query(
          `INSERT INTO incidents (incident_id, description, dependency_name, materiality, severity, urgency, reported_at, created_at, updated_at, source, external_id, ingest_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [incident.incidentId, incident.description, incident.dependencyName ?? null, incident.materiality, incident.severity, incident.urgency,
            incident.reportedAt, now, now, incident.source ?? null, incident.externalId ?? null, incident.ingest === undefined ? null : JSON.stringify(incident.ingest)],
        );
      } catch (e) {
        if ((e as { code?: string }).code === 'ER_DUP_ENTRY') throw new DbError('UUID_EXISTS', 'The provided Incident_ID already exists in the system.');
        throw e;
      }
      await this.audit(c, incident.incidentId, 'INCIDENT_CREATED', { ...incident, ingest: undefined });
      return incident;
    });
  }

  async editIncident(incidentId: string, changes: Partial<Omit<Incident, 'incidentId'>>) {
    const columns: Record<string, string> = {
      description: 'description', dependencyName: 'dependency_name', materiality: 'materiality',
      severity: 'severity', urgency: 'urgency', reportedAt: 'reported_at',
    };
    const sets = Object.entries(changes).filter(([k, v]) => k in columns && v !== undefined);
    return this.tx(async c => {
      await this.incident(c, incidentId);
      if (sets.length) {
        await c.query(
          `UPDATE incidents SET ${sets.map(([k]) => `${columns[k]} = ?`).join(', ')}, updated_at = ? WHERE incident_id = ?`,
          [...sets.map(([k, v]) => (k === 'dependencyName' && v === '' ? null : v)), new Date(), incidentId],
        );
      }
      await this.audit(c, incidentId, 'INCIDENT_EDITED', changes);
      return this.incident(c, incidentId);
    });
  }

  async getIncident(incidentId: string) {
    return this.tx(async c => {
      const incident = await this.incident(c, incidentId);
      await this.audit(c, incidentId, 'INCIDENT_READ', {});
      return incident;
    });
  }

  async listIncidents() {
    return (await this.rows(this.pool, 'SELECT * FROM incidents ORDER BY created_at, incident_id')).map(toIncident);
  }

  async findIncidentBySource(source: string, externalId: string) {
    const [r] = await this.rows(this.pool, 'SELECT * FROM incidents WHERE source = ? AND external_id = ?', [source, externalId]);
    return r ? toIncident(r) : undefined;
  }

  // /tickets

  async createTicket(incidentId: string, t: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[]; reportedAt: Date }) {
    return this.tx(async c => {
      // Lock the incident row (not a gap) so concurrent new tickets on it queue for the next number
      if (!(await this.rows(c, 'SELECT 1 FROM incidents WHERE incident_id = ? FOR UPDATE', [incidentId])).length) {
        throw new DbError('UUID_DNE', 'The specified Incident_ID does not exist.');
      }
      const [{ n }] = await this.rows(c, 'SELECT COALESCE(MAX(ticket_number), 0) + 1 AS n FROM ticket_versions WHERE incident_id = ?', [incidentId]);
      const ticketNumber = Number(n);
      await this.insertVersion(c, {
        incidentId, ticketNumber, version: 1, description: t.description,
        severity: t.severity ?? 'UNDECIDED', urgency: t.urgency ?? 'UNDECIDED', teams: t.teams ?? [], reportedAt: t.reportedAt,
      });
      const ticket = await this.ticket(c, incidentId, ticketNumber);
      await this.audit(c, incidentId, 'TICKET_CREATED', ticket);
      return ticket;
    });
  }

  async editTicket(incidentId: string, ticketNumber: number, changes: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[] }) {
    return this.tx(async c => {
      const latest = await this.ticket(c, incidentId, ticketNumber);
      await this.insertVersion(c, {
        incidentId, ticketNumber, version: latest.version + 1, description: changes.description,
        severity: changes.severity ?? latest.severity, urgency: changes.urgency ?? latest.urgency,
        teams: changes.teams ?? latest.teams, reportedAt: new Date(),
      });
      const ticket = await this.ticket(c, incidentId, ticketNumber);
      await this.audit(c, incidentId, 'TICKET_EDITED', ticket);
      return ticket;
    });
  }

  async getTicket(incidentId: string, ticketNumber: number, version?: number) {
    return this.tx(async c => {
      const ticket = await this.ticket(c, incidentId, ticketNumber, version);
      await this.audit(c, incidentId, 'TICKET_READ', { ticketId: ticket.ticketId });
      return ticket;
    });
  }

  async listTickets() {
    const keys = await this.rows(this.pool, 'SELECT DISTINCT incident_id, ticket_number FROM ticket_versions ORDER BY incident_id, ticket_number');
    return Promise.all(keys.map(k => this.ticket(this.pool, k.incident_id, k.ticket_number)));
  }

  async listTicketIds(incidentId: string) {
    await this.incident(this.pool, incidentId);
    const rows = await this.rows(this.pool, 'SELECT ticket_number, version FROM ticket_versions WHERE incident_id = ? ORDER BY created_at, ticket_number, version', [incidentId]);
    return rows.map(r => `${incidentId}_${r.ticket_number}_${r.version}`);
  }

  // /notifier

  async notifyTeams(incidentId: string, ticketNumber: number, teams: string[]) {
    await this.tx(async c => {
      await this.ticket(c, incidentId, ticketNumber);
      for (const team of teams) {
        await c.query('INSERT INTO notifications (incident_id, ticket_number, team_name, notified_at) VALUES (?, ?, ?, ?)', [incidentId, ticketNumber, team, new Date()]);
      }
      await this.audit(c, incidentId, 'TEAMS_NOTIFIED', { ticketNumber, teams });
    });
  }

  async claimTicket(incidentId: string, ticketNumber: number, team: string) {
    await this.tx(async c => {
      const { claimedBy } = await this.ticket(c, incidentId, ticketNumber);
      if (claimedBy && claimedBy !== team) throw new DbError('INVALID_DATA', `Ticket is already claimed by ${claimedBy}.`);
      if (!claimedBy) {
        await c.query('INSERT INTO ticket_claims (incident_id, ticket_number, team_name, claimed_at) VALUES (?, ?, ?, ?)', [incidentId, ticketNumber, team, new Date()]);
      }
      await this.audit(c, incidentId, 'TICKET_CLAIMED', { ticketNumber, team });
    });
  }

  // teams

  async createTeam(name: string, responsibility?: string) {
    await this.pool.query('INSERT INTO teams (team_name, responsibility, created_at) VALUES (?, ?, ?)', [name, responsibility ?? null, new Date()]);
  }

  async listTeams() {
    const rows = await this.rows(this.pool, 'SELECT team_name, responsibility FROM teams ORDER BY created_at, team_name');
    return rows.map(r => ({ name: r.team_name, responsibility: r.responsibility ?? undefined }));
  }

  // /dependencies

  async addDependency(name: string, source: 'MANUAL' | 'AUTO' = 'MANUAL') {
    await this.tx(async c => {
      try {
        await c.query('INSERT INTO dependencies (dp_name, source, created_at) VALUES (?, ?, ?)', [name, source, new Date()]);
      } catch (e) {
        if ((e as { code?: string }).code === 'ER_DUP_ENTRY') throw new DbError('DP_EXISTS', 'The dependency name already exists in the system.');
        throw e;
      }
      await this.audit(c, undefined, 'DEPENDENCY_ADDED', { name, source });
    });
  }

  async hasDependency(name: string) {
    return (await this.rows(this.pool, 'SELECT 1 FROM dependencies WHERE dp_name = ?', [name])).length > 0;
  }

  async removeDependency(name: string) {
    await this.tx(async c => {
      const [result] = await c.query<mysql.ResultSetHeader>('DELETE FROM dependencies WHERE dp_name = ?', [name]);
      if (result.affectedRows === 0) throw new DbError('DP_DNE', 'The dependency name does not exist in the system.');
      await this.audit(c, undefined, 'DEPENDENCY_REMOVED', { name });
    });
  }

  async listDependencies() {
    return (await this.rows(this.pool, 'SELECT dp_name FROM dependencies ORDER BY created_at')).map(r => r.dp_name as string);
  }

  // /logs

  async logEvent(incidentId: string | undefined, eventType: string, payload: unknown) {
    await this.tx(c => this.audit(c, incidentId, eventType, payload));
  }

  async getAuditLog(incidentId: string): Promise<AuditEntry[]> {
    const rows = await this.rows(this.pool, 'SELECT * FROM audit_log WHERE incident_id = ? ORDER BY seq', [incidentId]);
    return rows.map(r => ({
      seq: Number(r.seq), occurredAt: r.occurred_at, incidentId: r.incident_id ?? undefined,
      eventType: r.event_type, actor: r.actor ?? undefined, payload: JSON.parse(r.payload_json), hash: r.hash,
    }));
  }

  async verifyAuditChain() {
    let prev = GENESIS;
    for (const r of await this.rows(this.pool, 'SELECT * FROM audit_log ORDER BY seq')) {
      const seq = Number(r.seq);
      if (r.prev_hash !== prev || chainHash(prev, seq, r.occurred_at, r.incident_id, r.event_type, r.payload_json) !== r.hash) {
        return { ok: false, brokenAtSeq: seq };
      }
      prev = r.hash;
    }
    return { ok: true };
  }

  // /reset (testing only)

  async reset() {
    const c = await this.pool.getConnection();
    try {
      await c.query('SET FOREIGN_KEY_CHECKS = 0');
      for (const table of ['audit_log', 'notifications', 'ticket_claims', 'ticket_version_teams', 'ticket_versions', 'incidents', 'dependencies', 'teams']) {
        await c.query(`TRUNCATE TABLE ${table}`);
      }
      await c.query('SET FOREIGN_KEY_CHECKS = 1');
      await c.query('UPDATE audit_head SET seq = 0, hash = ? WHERE id = 1', [GENESIS]);
      for (const name of DEFAULT_TEAMS) await c.query('INSERT INTO teams (team_name, created_at) VALUES (?, ?)', [name, new Date()]);
    } finally {
      c.release();
    }
  }
}
