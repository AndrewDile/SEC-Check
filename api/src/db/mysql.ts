// MySQL implementation of the Database interface (schema: db/migrations). Every query is limited to the
// current request's scope (context.ts).
import { createHash } from 'node:crypto';
import mysql, { type Pool, type PoolConnection, type ResultSetHeader, type RowDataPacket } from 'mysql2/promise';
import { addBusinessDays, FILING_BUSINESS_DAYS, newYorkDate } from '../calendar.js';
import { current } from '../context.js';
import {
  type AuditEntry,
  type Contact,
  type Database,
  DbError,
  type Incident,
  type Severity,
  type Ticket,
  type Urgency,
  type User,
  type UserFields,
} from './api.js';

const DEFAULT_TEAMS = ['LEGAL', 'CYBER1', 'CYBER2'];
// The web app's settings.json users and their teams
const DEFAULT_USERS: Record<string, string[]> = {
  alice: ['CYBER1'],
  bob: ['CYBER2'],
  carol: ['LEGAL'],
  dana: ['LEGAL', 'CYBER1'],
  'core-gateway': ['LEGAL', 'CYBER1', 'CYBER2'],
};
const GENESIS = '0'.repeat(64);
// Children before parents, for deletes
const SCOPED_TABLES = [
  'team_members',
  'ticket_version_teams',
  'ticket_claims',
  'notifications',
  'ticket_versions',
  'incidents',
  'dependencies',
  'users',
  'teams',
  'audit_log',
  'audit_head',
];
const INCIDENT_COLUMNS: Record<string, string> = {
  description: 'description',
  dependencyName: 'dependency_name',
  materiality: 'materiality',
  severity: 'severity',
  urgency: 'urgency',
  reportedAt: 'reported_at',
};

type Conn = Pool | PoolConnection;

const code = (e: unknown) => (e as { code?: string }).code;
const pick = (o: object, keys: string[]) => Object.fromEntries(keys.map((k) => [k, (o as Record<string, unknown>)[k]]));

// hash = SHA-256(prev_hash + row); actor joined the row in Phase 4, so older rows (actor NULL) still verify
function chainHash(
  prev: string,
  seq: number,
  occurredAt: Date,
  incidentId: string | null,
  eventType: string,
  payloadJson: string,
  actor: string | null,
) {
  const row = [seq, occurredAt.toISOString(), incidentId, eventType, payloadJson, ...(actor === null ? [] : [actor])];
  return createHash('sha256')
    .update(prev + JSON.stringify(row))
    .digest('hex');
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
    materialAt: r.material_at ?? undefined,
    filingDeadline: r.filing_deadline ?? undefined,
    source: r.source ?? undefined,
    externalId: r.external_id ?? undefined,
    ingest: r.ingest_json ?? undefined,
  };
}

function toEntry(r: RowDataPacket): AuditEntry {
  return {
    seq: Number(r.seq),
    occurredAt: r.occurred_at,
    incidentId: r.incident_id ?? undefined,
    eventType: r.event_type,
    actor: r.actor ?? undefined,
    payload: JSON.parse(r.payload_json),
    hash: r.hash,
  };
}

export class MySqlDb implements Database {
  constructor(private pool: Pool) {}

  static fromEnv() {
    return new MySqlDb(
      mysql.createPool({
        host: process.env.DB_HOST ?? 'localhost',
        port: Number(process.env.DB_PORT ?? 3306),
        user: process.env.DB_USER,
        password: process.env.DB_PASSWORD,
        database: process.env.DB_NAME ?? 'seccheck',
        connectionLimit: Number(process.env.DB_POOL_SIZE ?? 10),
        timezone: 'Z',
        dateStrings: ['DATE'],
      }),
    );
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
        if (code(e) !== 'ER_LOCK_DEADLOCK' || attempt === 5) throw e;
        await new Promise((r) => setTimeout(r, Math.random() * 20 * attempt));
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
      if (code(e) === 'ER_NO_REFERENCED_ROW_2') throw new DbError('INVALID_DATA', 'Unknown team name.');
      if (code(e) === 'ER_DATA_TOO_LONG' || code(e) === 'WARN_DATA_TRUNCATED')
        throw new DbError('INVALID_DATA', 'A field is too long or has an invalid value.');
      throw e;
    } finally {
      c.release();
    }
  }

  private async audit(c: Conn, incidentId: string | undefined, eventType: string, payload: unknown) {
    const { scope, actor } = current();
    const [head] = await this.rows(c, 'SELECT seq, hash FROM audit_head WHERE scope_id = ? FOR UPDATE', [scope]);
    const seq = Number(head.seq) + 1;
    const occurredAt = new Date();
    const payloadJson = JSON.stringify(payload ?? {});
    const hash = chainHash(head.hash, seq, occurredAt, incidentId ?? null, eventType, payloadJson, actor);
    await c.query(
      'INSERT INTO audit_log (scope_id, seq, occurred_at, incident_id, event_type, actor, payload_json, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
      [scope, seq, occurredAt, incidentId ?? null, eventType, actor, payloadJson, head.hash, hash],
    );
    await c.query('UPDATE audit_head SET seq = ?, hash = ? WHERE scope_id = ?', [seq, hash, scope]);
  }

  private async incident(c: Conn, incidentId: string, lock = false): Promise<Incident> {
    const [r] = await this.rows(
      c,
      `SELECT * FROM incidents WHERE scope_id = ? AND incident_id = ?${lock ? ' FOR UPDATE' : ''}`,
      [current().scope, incidentId],
    );
    if (!r) throw new DbError('UUID_DNE', 'The specified Incident_ID does not exist.');
    return toIncident(r);
  }

  private async deadline(c: Conn, materialAt: Date) {
    const start = newYorkDate(materialAt);
    const holidays = await this.rows(
      c,
      'SELECT day FROM business_calendar WHERE day > ? AND day <= ? + INTERVAL 1 MONTH',
      [start, start],
    );
    return addBusinessDays(start, FILING_BUSINESS_DAYS, new Set(holidays.map((h) => h.day)));
  }

  // Teams, claim and incident for ticket_versions rows, in three queries however many rows there are
  private async withDetails(c: Conn, rows: RowDataPacket[]): Promise<Ticket[]> {
    if (!rows.length) return [];
    const { scope } = current();
    const ids = [...new Set(rows.map((r) => r.incident_id as string))];
    const id = (r: RowDataPacket) => `${r.incident_id}_${r.ticket_number}`;
    const teams = new Map<string, string[]>();
    for (const t of await this.rows(
      c,
      'SELECT incident_id, ticket_number, version, team_name FROM ticket_version_teams WHERE scope_id = ? AND (incident_id, ticket_number, version) IN (?) ORDER BY team_name',
      [scope, rows.map((r) => [r.incident_id, r.ticket_number, r.version])],
    )) {
      teams.set(`${id(t)}_${t.version}`, [...(teams.get(`${id(t)}_${t.version}`) ?? []), t.team_name]);
    }
    const claims = await this.rows(
      c,
      'SELECT incident_id, ticket_number, team_name FROM ticket_claims WHERE scope_id = ? AND incident_id IN (?) ORDER BY claim_id',
      [scope, ids],
    );
    const claimedBy = new Map(claims.map((r) => [id(r), r.team_name as string])); // latest claim wins
    const incidents = new Map(
      (await this.rows(c, 'SELECT * FROM incidents WHERE scope_id = ? AND incident_id IN (?)', [scope, ids])).map(
        (r) => [r.incident_id as string, toIncident(r)],
      ),
    );
    return rows.map((r) => ({
      ticketId: `${id(r)}_${r.version}`,
      incidentId: r.incident_id,
      ticketNumber: r.ticket_number,
      version: r.version,
      description: r.description,
      severity: r.severity,
      urgency: r.urgency,
      teams: teams.get(`${id(r)}_${r.version}`) ?? [],
      claimedBy: claimedBy.get(id(r)),
      reportedAt: r.reported_at,
      incident: incidents.get(r.incident_id)!,
    }));
  }

  private async ticket(c: Conn, incidentId: string, ticketNumber: number, version?: number): Promise<Ticket> {
    await this.incident(c, incidentId);
    const params = [current().scope, incidentId, ticketNumber];
    const [r] =
      version === undefined
        ? await this.rows(
            c,
            'SELECT * FROM ticket_versions WHERE scope_id = ? AND incident_id = ? AND ticket_number = ? ORDER BY version DESC LIMIT 1',
            params,
          )
        : await this.rows(
            c,
            'SELECT * FROM ticket_versions WHERE scope_id = ? AND incident_id = ? AND ticket_number = ? AND version = ?',
            [...params, version],
          );
    if (!r) throw new DbError('UUID_DNE', 'The specified ticket does not exist.');
    return (await this.withDetails(c, [r]))[0];
  }

  private async insertVersion(c: Conn, t: Omit<Ticket, 'ticketId' | 'claimedBy' | 'incident'>) {
    const { scope } = current();
    await c.query(
      'INSERT INTO ticket_versions (scope_id, incident_id, ticket_number, version, description, severity, urgency, reported_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
      [scope, t.incidentId, t.ticketNumber, t.version, t.description, t.severity, t.urgency, t.reportedAt, new Date()],
    );
    if (t.teams.length) {
      await c.query(
        'INSERT INTO ticket_version_teams (scope_id, incident_id, ticket_number, version, team_name) VALUES ?',
        [t.teams.map((team) => [scope, t.incidentId, t.ticketNumber, t.version, team])],
      );
    }
  }

  // Default teams, users and memberships, and the audit genesis, for a new or wiped scope
  private async seed(c: Conn, scope: number) {
    const now = Date.now();
    await c.query('INSERT INTO teams (scope_id, team_name, created_at) VALUES ?', [
      DEFAULT_TEAMS.map((t, i) => [scope, t, new Date(now + i)]),
    ]);
    await c.query('INSERT INTO users (scope_id, username, created_at) VALUES ?', [
      Object.keys(DEFAULT_USERS).map((u) => [scope, u, new Date(now)]),
    ]);
    await c.query('INSERT INTO team_members (scope_id, team_name, username, added_at) VALUES ?', [
      Object.entries(DEFAULT_USERS).flatMap(([u, teams]) => teams.map((t) => [scope, t, u, new Date(now)])),
    ]);
    await c.query('INSERT INTO audit_head (scope_id, seq, hash) VALUES (?, 0, ?)', [scope, GENESIS]);
  }

  // Deletes a scope's rows; the append-only triggers allow it only while @seccheck_purge is set
  private async purge(c: PoolConnection, scope: number) {
    await c.query('SET @seccheck_purge = 1');
    try {
      for (const table of SCOPED_TABLES) await c.query(`DELETE FROM ${table} WHERE scope_id = ?`, [scope]);
    } finally {
      await c.query('SET @seccheck_purge = NULL');
    }
  }

  // /incidents

  async createIncident(i: Omit<Incident, 'materiality' | 'severity' | 'urgency'> & Partial<Incident>) {
    const now = new Date();
    return this.tx(async (c) => {
      const incident: Incident = {
        ...i,
        materiality: i.materiality ?? 'UNDECIDED',
        severity: i.severity ?? 'UNDECIDED',
        urgency: i.urgency ?? 'UNDECIDED',
        ...(i.materiality === 'MATERIAL' && { materialAt: now, filingDeadline: await this.deadline(c, now) }),
      };
      try {
        await c.query(
          `INSERT INTO incidents (scope_id, incident_id, description, dependency_name, materiality, severity, urgency, material_at, filing_deadline, reported_at, created_at, updated_at, source, external_id, ingest_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            current().scope,
            incident.incidentId,
            incident.description,
            incident.dependencyName ?? null,
            incident.materiality,
            incident.severity,
            incident.urgency,
            incident.materialAt ?? null,
            incident.filingDeadline ?? null,
            incident.reportedAt,
            now,
            now,
            incident.source ?? null,
            incident.externalId ?? null,
            incident.ingest === undefined ? null : JSON.stringify(incident.ingest),
          ],
        );
      } catch (e) {
        if (code(e) === 'ER_DUP_ENTRY')
          throw new DbError('UUID_EXISTS', 'The provided Incident_ID already exists in the system.');
        throw e;
      }
      await this.audit(c, incident.incidentId, 'INCIDENT_CREATED', { ...incident, ingest: undefined });
      return incident;
    });
  }

  async editIncident(incidentId: string, changes: Partial<Omit<Incident, 'incidentId'>>, note?: string) {
    const keys = Object.keys(changes).filter(
      (k) => k in INCIDENT_COLUMNS && changes[k as keyof typeof changes] !== undefined,
    );
    return this.tx(async (c) => {
      const before = await this.incident(c, incidentId, true);
      const reversal =
        before.materiality === 'MATERIAL' && changes.materiality !== undefined && changes.materiality !== 'MATERIAL';
      if (reversal && !note?.trim())
        throw new DbError('INVALID_DATA', 'A Note is required to change Materiality away from MATERIAL.');
      const sets: [string, unknown][] = keys.map((k) => {
        const v = changes[k as keyof typeof changes];
        return [INCIDENT_COLUMNS[k], k === 'dependencyName' && v === '' ? null : v];
      });
      // The deadline runs from the first MATERIAL determination and is never restarted
      if (changes.materiality === 'MATERIAL' && !before.materialAt) {
        const now = new Date();
        sets.push(['material_at', now], ['filing_deadline', await this.deadline(c, now)]);
      }
      if (sets.length) {
        await c.query(
          `UPDATE incidents SET ${sets.map(([col]) => `${col} = ?`).join(', ')}, updated_at = ? WHERE scope_id = ? AND incident_id = ?`,
          [...sets.map(([, v]) => v), new Date(), current().scope, incidentId],
        );
      }
      const after = await this.incident(c, incidentId);
      await this.audit(c, incidentId, reversal ? 'MATERIALITY_REVERSED' : 'INCIDENT_EDITED', {
        before: pick(before, keys),
        after: pick(after, keys),
        ...(note && { note }),
      });
      return after;
    });
  }

  async getIncident(incidentId: string) {
    return this.tx(async (c) => {
      const incident = await this.incident(c, incidentId);
      await this.audit(c, incidentId, 'INCIDENT_READ', {});
      return incident;
    });
  }

  async listIncidents() {
    return (
      await this.rows(this.pool, 'SELECT * FROM incidents WHERE scope_id = ? ORDER BY created_at, incident_id', [
        current().scope,
      ])
    ).map(toIncident);
  }

  async findIncidentBySource(source: string, externalId: string) {
    const [r] = await this.rows(
      this.pool,
      'SELECT * FROM incidents WHERE scope_id = ? AND source = ? AND external_id = ?',
      [current().scope, source, externalId],
    );
    return r ? toIncident(r) : undefined;
  }

  // /tickets

  async createTicket(
    incidentId: string,
    t: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[]; reportedAt: Date },
  ) {
    return this.tx(async (c) => {
      // Lock the incident row (not a gap) so concurrent new tickets on it queue for the next number
      await this.incident(c, incidentId, true);
      const [{ n }] = await this.rows(
        c,
        'SELECT COALESCE(MAX(ticket_number), 0) + 1 AS n FROM ticket_versions WHERE scope_id = ? AND incident_id = ?',
        [current().scope, incidentId],
      );
      const ticketNumber = Number(n);
      await this.insertVersion(c, {
        incidentId,
        ticketNumber,
        version: 1,
        description: t.description,
        severity: t.severity ?? 'UNDECIDED',
        urgency: t.urgency ?? 'UNDECIDED',
        teams: t.teams ?? [],
        reportedAt: t.reportedAt,
      });
      const ticket = await this.ticket(c, incidentId, ticketNumber);
      await this.audit(c, incidentId, 'TICKET_CREATED', { ...ticket, incident: undefined });
      return ticket;
    });
  }

  async editTicket(
    incidentId: string,
    ticketNumber: number,
    changes: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[] },
  ) {
    return this.tx(async (c) => {
      await this.incident(c, incidentId, true); // concurrent edits queue for the next version
      const latest = await this.ticket(c, incidentId, ticketNumber);
      await this.insertVersion(c, {
        incidentId,
        ticketNumber,
        version: latest.version + 1,
        description: changes.description,
        severity: changes.severity ?? latest.severity,
        urgency: changes.urgency ?? latest.urgency,
        teams: changes.teams ?? latest.teams,
        reportedAt: new Date(),
      });
      const ticket = await this.ticket(c, incidentId, ticketNumber);
      await this.audit(c, incidentId, 'TICKET_EDITED', { ...ticket, incident: undefined });
      return ticket;
    });
  }

  async getTicket(incidentId: string, ticketNumber: number, version?: number) {
    return this.tx(async (c) => {
      const ticket = await this.ticket(c, incidentId, ticketNumber, version);
      await this.audit(c, incidentId, 'TICKET_READ', { ticketId: ticket.ticketId });
      return ticket;
    });
  }

  async listTickets() {
    return this.tx(async (c) =>
      this.withDetails(
        c,
        await this.rows(
          c,
          `SELECT * FROM ticket_versions v WHERE scope_id = ? AND version = (SELECT MAX(version) FROM ticket_versions m
             WHERE m.scope_id = v.scope_id AND m.incident_id = v.incident_id AND m.ticket_number = v.ticket_number)
           ORDER BY incident_id, ticket_number`,
          [current().scope],
        ),
      ),
    );
  }

  async listTicketIds(incidentId: string) {
    return this.tx(async (c) => {
      await this.incident(c, incidentId);
      return this.ticketIds(c, incidentId);
    });
  }

  private async ticketIds(c: Conn, incidentId: string) {
    const rows = await this.rows(
      c,
      'SELECT ticket_number, version FROM ticket_versions WHERE scope_id = ? AND incident_id = ? ORDER BY created_at, ticket_number, version',
      [current().scope, incidentId],
    );
    return rows.map((r) => `${incidentId}_${r.ticket_number}_${r.version}`);
  }

  // /notifier

  async notifyTeams(incidentId: string, ticketNumber: number, teams: string[]) {
    await this.tx(async (c) => {
      await this.ticket(c, incidentId, ticketNumber);
      const now = new Date();
      await c.query(
        'INSERT INTO notifications (scope_id, incident_id, ticket_number, team_name, notified_at) VALUES ?',
        [teams.map((team) => [current().scope, incidentId, ticketNumber, team, now])],
      );
      await this.audit(c, incidentId, 'TEAMS_NOTIFIED', { ticketNumber, teams });
    });
  }

  async claimTicket(incidentId: string, ticketNumber: number, team: string) {
    await this.tx(async (c) => {
      await this.incident(c, incidentId, true); // two teams claiming at once queue, so only one wins
      const { claimedBy } = await this.ticket(c, incidentId, ticketNumber);
      if (claimedBy && claimedBy !== team)
        throw new DbError('INVALID_DATA', `Ticket is already claimed by ${claimedBy}.`);
      if (!claimedBy) {
        await c.query(
          'INSERT INTO ticket_claims (scope_id, incident_id, ticket_number, team_name, claimed_at) VALUES (?, ?, ?, ?, ?)',
          [current().scope, incidentId, ticketNumber, team, new Date()],
        );
      }
      await this.audit(c, incidentId, 'TICKET_CLAIMED', { ticketNumber, team });
    });
  }

  // /teams

  private async requireTeam(c: Conn, name: string, lock = false) {
    const sql = `SELECT 1 FROM teams WHERE scope_id = ? AND team_name = ?${lock ? ' FOR UPDATE' : ''}`;
    if (!(await this.rows(c, sql, [current().scope, name])).length)
      throw new DbError('TEAM_DNE', 'The team name does not exist in the system.');
  }

  async createTeam(name: string, responsibility?: string) {
    await this.tx(async (c) => {
      try {
        await c.query('INSERT INTO teams (scope_id, team_name, responsibility, created_at) VALUES (?, ?, ?, ?)', [
          current().scope,
          name,
          responsibility ?? null,
          new Date(),
        ]);
      } catch (e) {
        if (code(e) === 'ER_DUP_ENTRY') throw new DbError('TEAM_EXISTS', 'The team name already exists in the system.');
        throw e;
      }
      await this.audit(c, undefined, 'TEAM_CREATED', { name });
    });
  }

  async removeTeam(name: string) {
    await this.tx(async (c) => {
      const { scope } = current();
      await this.requireTeam(c, name, true);
      // Tickets, notifications and claims are append-only history, so a team they refer to stays.
      for (const table of ['ticket_version_teams', 'notifications', 'ticket_claims']) {
        if (
          (await this.rows(c, `SELECT 1 FROM ${table} WHERE scope_id = ? AND team_name = ? LIMIT 1`, [scope, name]))
            .length
        )
          throw new DbError('INVALID_DATA', `Team ${name} is used by existing tickets and can't be removed.`);
      }
      await c.query('DELETE FROM team_members WHERE scope_id = ? AND team_name = ?', [scope, name]);
      await c.query('DELETE FROM teams WHERE scope_id = ? AND team_name = ?', [scope, name]);
      await this.audit(c, undefined, 'TEAM_REMOVED', { name });
    });
  }

  async getTeam(name: string) {
    await this.requireTeam(this.pool, name);
    const rows = await this.rows(
      this.pool,
      'SELECT username FROM team_members WHERE scope_id = ? AND team_name = ? ORDER BY added_at, username',
      [current().scope, name],
    );
    return { name, members: rows.map((r) => r.username as string) };
  }

  async listTeams() {
    const rows = await this.rows(
      this.pool,
      'SELECT team_name, responsibility FROM teams WHERE scope_id = ? ORDER BY created_at, team_name',
      [current().scope],
    );
    return rows.map((r) => ({ name: r.team_name, responsibility: r.responsibility ?? undefined }));
  }

  async addMember(team: string, username: string) {
    await this.tx(async (c) => {
      await this.requireTeam(c, team, true);
      await this.user(c, username);
      try {
        await c.query('INSERT INTO team_members (scope_id, team_name, username, added_at) VALUES (?, ?, ?, ?)', [
          current().scope,
          team,
          username,
          new Date(),
        ]);
      } catch (e) {
        if (code(e) === 'ER_DUP_ENTRY') throw new DbError('USER_EXISTS', 'The user is already a member of the team.');
        throw e;
      }
      await this.audit(c, undefined, 'TEAM_MEMBER_ADDED', { team, username });
    });
  }

  async removeMember(team: string, username: string) {
    await this.tx(async (c) => {
      await this.requireTeam(c, team, true);
      const [result] = await c.query<ResultSetHeader>(
        'DELETE FROM team_members WHERE scope_id = ? AND team_name = ? AND username = ?',
        [current().scope, team, username],
      );
      if (result.affectedRows === 0) throw new DbError('USER_DNE', 'The user is not a member of the team.');
      await this.audit(c, undefined, 'TEAM_MEMBER_REMOVED', { team, username });
    });
  }

  async listContacts(): Promise<Contact[]> {
    const rows = await this.rows(
      this.pool,
      `SELECT t.team_name, u.username, u.contact_channel, u.contact_address FROM teams t
       LEFT JOIN team_members m ON m.scope_id = t.scope_id AND m.team_name = t.team_name
       LEFT JOIN users u ON u.scope_id = m.scope_id AND u.username = m.username
       WHERE t.scope_id = ? ORDER BY t.created_at, t.team_name, u.username`,
      [current().scope],
    );
    return rows.map((r) =>
      r.username
        ? {
            team: r.team_name,
            username: r.username,
            channel: r.contact_channel,
            address: r.contact_address ?? r.username,
          }
        : { team: r.team_name, channel: 'log', address: r.team_name },
    );
  }

  // /users

  private async user(c: Conn, username: string, lock = false): Promise<User> {
    const { scope } = current();
    const [r] = await this.rows(
      c,
      `SELECT * FROM users WHERE scope_id = ? AND username = ?${lock ? ' FOR UPDATE' : ''}`,
      [scope, username],
    );
    if (!r) throw new DbError('USER_DNE', 'The user does not exist in the system.');
    const teams = await this.rows(
      c,
      'SELECT team_name FROM team_members WHERE scope_id = ? AND username = ? ORDER BY team_name',
      [scope, username],
    );
    return {
      username: r.username,
      displayName: r.display_name ?? undefined,
      contactChannel: r.contact_channel,
      contactAddress: r.contact_address ?? undefined,
      teams: teams.map((t) => t.team_name),
    };
  }

  async createUser(u: { username: string } & UserFields) {
    return this.tx(async (c) => {
      try {
        await c.query(
          'INSERT INTO users (scope_id, username, display_name, contact_channel, contact_address, auth_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
          [
            current().scope,
            u.username,
            u.displayName ?? null,
            u.contactChannel ?? 'log',
            u.contactAddress ?? null,
            u.authHash ?? null,
            new Date(),
          ],
        );
      } catch (e) {
        if (code(e) === 'ER_DUP_ENTRY') throw new DbError('USER_EXISTS', 'The user already exists in the system.');
        throw e;
      }
      const user = await this.user(c, u.username);
      await this.audit(c, undefined, 'USER_CREATED', user);
      return user;
    });
  }

  async editUser(username: string, changes: UserFields) {
    const columns: Record<string, string> = {
      displayName: 'display_name',
      contactChannel: 'contact_channel',
      contactAddress: 'contact_address',
      authHash: 'auth_hash',
    };
    const sets = Object.entries(changes).filter(([k, v]) => k in columns && v !== undefined);
    return this.tx(async (c) => {
      const before = await this.user(c, username, true);
      if (sets.length) {
        await c.query(
          `UPDATE users SET ${sets.map(([k]) => `${columns[k]} = ?`).join(', ')} WHERE scope_id = ? AND username = ?`,
          [...sets.map(([, v]) => v), current().scope, username],
        );
      }
      const after = await this.user(c, username);
      const keys = sets.map(([k]) => k).filter((k) => k !== 'authHash');
      await this.audit(c, undefined, 'USER_EDITED', {
        username,
        before: pick(before, keys),
        after: pick(after, keys),
        ...(changes.authHash && { credential: 'replaced' }),
      });
      return after;
    });
  }

  async getUser(username: string) {
    return this.user(this.pool, username);
  }

  async removeUser(username: string) {
    await this.tx(async (c) => {
      await this.user(c, username, true);
      await c.query('DELETE FROM team_members WHERE scope_id = ? AND username = ?', [current().scope, username]);
      await c.query('DELETE FROM users WHERE scope_id = ? AND username = ?', [current().scope, username]);
      await this.audit(c, undefined, 'USER_REMOVED', { username });
    });
  }

  async listUsers() {
    const names = await this.rows(
      this.pool,
      'SELECT username FROM users WHERE scope_id = ? ORDER BY created_at, username',
      [current().scope],
    );
    return Promise.all(names.map((r) => this.user(this.pool, r.username)));
  }

  async hasUser(username: string) {
    return (
      (
        await this.rows(this.pool, 'SELECT 1 FROM users WHERE scope_id = ? AND username = ?', [
          current().scope,
          username,
        ])
      ).length > 0
    );
  }

  // /dependencies

  async addDependency(name: string, source: 'MANUAL' | 'AUTO' = 'MANUAL') {
    await this.tx(async (c) => {
      try {
        await c.query('INSERT INTO dependencies (scope_id, dp_name, source, created_at) VALUES (?, ?, ?, ?)', [
          current().scope,
          name,
          source,
          new Date(),
        ]);
      } catch (e) {
        if (code(e) === 'ER_DUP_ENTRY')
          throw new DbError('DP_EXISTS', 'The dependency name already exists in the system.');
        throw e;
      }
      await this.audit(c, undefined, 'DEPENDENCY_ADDED', { name, source });
    });
  }

  async hasDependency(name: string) {
    return (
      (
        await this.rows(this.pool, 'SELECT 1 FROM dependencies WHERE scope_id = ? AND dp_name = ?', [
          current().scope,
          name,
        ])
      ).length > 0
    );
  }

  async removeDependency(name: string) {
    await this.tx(async (c) => {
      const [result] = await c.query<ResultSetHeader>('DELETE FROM dependencies WHERE scope_id = ? AND dp_name = ?', [
        current().scope,
        name,
      ]);
      if (result.affectedRows === 0) throw new DbError('DP_DNE', 'The dependency name does not exist in the system.');
      await this.audit(c, undefined, 'DEPENDENCY_REMOVED', { name });
    });
  }

  async listDependencies() {
    return (
      await this.rows(this.pool, 'SELECT dp_name FROM dependencies WHERE scope_id = ? ORDER BY created_at', [
        current().scope,
      ])
    ).map((r) => r.dp_name as string);
  }

  // /logs

  async getLog(incidentId: string) {
    return this.tx(async (c) => {
      const incident = await this.incident(c, incidentId);
      const ticketIds = await this.ticketIds(c, incidentId);
      const entries = (
        await this.rows(c, 'SELECT * FROM audit_log WHERE scope_id = ? AND incident_id = ? ORDER BY seq', [
          current().scope,
          incidentId,
        ])
      ).map(toEntry);
      await this.audit(c, incidentId, 'LOG_READ', {});
      return { incident, ticketIds, entries };
    });
  }

  async logEvent(incidentId: string | undefined, eventType: string, payload: unknown) {
    await this.tx((c) => this.audit(c, incidentId, eventType, payload));
  }

  async getAuditLog(incidentId: string): Promise<AuditEntry[]> {
    const rows = await this.rows(
      this.pool,
      'SELECT * FROM audit_log WHERE scope_id = ? AND incident_id = ? ORDER BY seq',
      [current().scope, incidentId],
    );
    return rows.map(toEntry);
  }

  async verifyAuditChain() {
    let prev = GENESIS;
    for (const r of await this.rows(this.pool, 'SELECT * FROM audit_log WHERE scope_id = ? ORDER BY seq', [
      current().scope,
    ])) {
      const seq = Number(r.seq);
      if (
        r.prev_hash !== prev ||
        chainHash(prev, seq, r.occurred_at, r.incident_id, r.event_type, r.payload_json, r.actor) !== r.hash
      ) {
        return { ok: false, brokenAtSeq: seq };
      }
      prev = r.hash;
    }
    return { ok: true };
  }

  // /reset

  async reset() {
    await this.tx(async (c) => {
      await this.purge(c, current().scope);
      await this.seed(c, current().scope);
    });
  }

  // test sessions

  async createSession(sessionId: string, clientIp?: string) {
    return this.tx(async (c) => {
      let scope: number;
      try {
        const [r] = await c.query<ResultSetHeader>(
          'INSERT INTO test_sessions (session_id, client_ip, started_at) VALUES (?, ?, ?)',
          [sessionId, clientIp ?? null, new Date()],
        );
        scope = r.insertId;
      } catch (e) {
        if (code(e) === 'ER_DUP_ENTRY') throw new DbError('UUID_EXISTS', `Session ${sessionId} was already used.`);
        throw e;
      }
      await this.seed(c, scope);
      return scope;
    });
  }

  async endSession(scope: number, report: unknown) {
    await this.pool.query('UPDATE test_sessions SET ended_at = ?, report_json = ? WHERE scope_id = ?', [
      new Date(),
      JSON.stringify(report),
      scope,
    ]);
  }

  async getSessionReport(sessionId: string) {
    const [r] = await this.rows(
      this.pool,
      'SELECT report_json FROM test_sessions WHERE session_id = ? AND ended_at IS NOT NULL',
      [sessionId],
    );
    return r?.report_json ?? undefined;
  }

  async endOpenSessions() {
    await this.pool.query('UPDATE test_sessions SET ended_at = ? WHERE ended_at IS NULL', [new Date()]);
  }

  async purgeEndedSessions(endedBefore: Date) {
    const ended = await this.rows(
      this.pool,
      'SELECT scope_id FROM test_sessions WHERE purged_at IS NULL AND ended_at < ?',
      [endedBefore],
    );
    for (const { scope_id } of ended) {
      await this.tx(async (c) => {
        await this.purge(c, scope_id);
        await c.query('UPDATE test_sessions SET purged_at = ? WHERE scope_id = ?', [new Date(), scope_id]);
      });
    }
    return ended.length;
  }
}
