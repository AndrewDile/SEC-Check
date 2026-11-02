// Methods the Core API calls to read/write the database. Each runs in one transaction, in the scope and
// as the actor of the current request (context.ts), and writes its audit_log entry in that transaction.
// Reads of incidents, tickets and logs are audited too (REQ-02); LIST accesses are audited by the caller.

export type Materiality = 'MATERIAL' | 'IMMATERIAL' | 'UNDECIDED';
export type Severity = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNDECIDED' | 'RESOLVED';
export type Urgency = 'URGENT' | 'NOT_URGENT' | 'UNDECIDED' | 'RESOLVED';
export type ErrorType =
  | 'UUID_EXISTS'
  | 'UUID_DNE'
  | 'INVALID_DATA'
  | 'DP_EXISTS'
  | 'DP_DNE'
  | 'TEAM_EXISTS'
  | 'TEAM_DNE'
  | 'USER_EXISTS'
  | 'USER_DNE'
  | 'TIMEOUT';

export class DbError extends Error {
  constructor(
    public type: ErrorType,
    message: string,
  ) {
    super(message);
  }
}

export interface Incident {
  incidentId: string;
  description: string;
  dependencyName?: string;
  materiality: Materiality;
  severity: Severity;
  urgency: Urgency;
  reportedAt: Date;
  materialAt?: Date; // first MATERIAL determination
  filingDeadline?: string; // YYYY-MM-DD, 4 business days after materialAt
  // Set when the ingestion worker reported it; (source, externalId) is unique
  source?: string;
  externalId?: string;
  ingest?: unknown; // the worker's payload, returned as-is on a repeat report
}

export interface Ticket {
  ticketId: string; // strong ID: <incident>_<ticket>_<version>
  incidentId: string;
  ticketNumber: number;
  version: number;
  description: string;
  severity: Severity;
  urgency: Urgency;
  teams: string[];
  claimedBy?: string;
  reportedAt: Date;
  incident: Incident; // read in the same transaction
}

export interface AuditEntry {
  seq: number;
  occurredAt: Date;
  incidentId?: string;
  eventType: string;
  actor?: string;
  payload: unknown;
  hash: string;
}

export interface User {
  username: string;
  displayName?: string;
  contactChannel: string;
  contactAddress?: string;
  teams: string[];
}

export interface UserFields {
  displayName?: string;
  contactChannel?: string;
  contactAddress?: string;
  authHash?: string; // already hashed for storage; never read back
}

export interface Contact {
  team: string;
  username?: string; // undefined for a team with no members
  channel: string;
  address: string;
}

export interface Database {
  // /incidents
  createIncident(
    incident: Omit<Incident, 'materiality' | 'severity' | 'urgency'> & Partial<Incident>,
  ): Promise<Incident>; // UUID_EXISTS
  // INVALID_DATA when a MATERIAL incident is changed to another materiality without a note
  editIncident(incidentId: string, changes: Partial<Omit<Incident, 'incidentId'>>, note?: string): Promise<Incident>;
  getIncident(incidentId: string): Promise<Incident>; // UUID_DNE
  listIncidents(): Promise<Incident[]>;
  findIncidentBySource(source: string, externalId: string): Promise<Incident | undefined>; // /ingest/incidents dedupe

  // /tickets
  createTicket(
    incidentId: string,
    ticket: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[]; reportedAt: Date },
  ): Promise<Ticket>;
  editTicket(
    incidentId: string,
    ticketNumber: number,
    changes: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[] },
  ): Promise<Ticket>; // new version
  getTicket(incidentId: string, ticketNumber: number, version?: number): Promise<Ticket>; // latest version unless given
  listTickets(): Promise<Ticket[]>; // latest version of every ticket, for the web app queue
  listTicketIds(incidentId: string): Promise<string[]>; // all strong IDs

  // /notifier
  notifyTeams(incidentId: string, ticketNumber: number, teams: string[]): Promise<void>;
  claimTicket(incidentId: string, ticketNumber: number, team: string): Promise<void>; // INVALID_DATA if claimed by another team

  // /teams
  createTeam(name: string, responsibility?: string): Promise<void>; // TEAM_EXISTS
  removeTeam(name: string): Promise<void>; // TEAM_DNE; INVALID_DATA while tickets, notifications or claims use it
  getTeam(name: string): Promise<{ name: string; members: string[] }>; // TEAM_DNE
  listTeams(): Promise<{ name: string; responsibility?: string }[]>;
  addMember(team: string, username: string): Promise<void>; // TEAM_DNE, USER_DNE; USER_EXISTS if already a member
  removeMember(team: string, username: string): Promise<void>; // TEAM_DNE; USER_DNE if not a member
  listContacts(): Promise<Contact[]>; // who to notify for each team

  // /users
  createUser(user: { username: string } & UserFields): Promise<User>; // USER_EXISTS
  editUser(username: string, changes: UserFields): Promise<User>; // USER_DNE
  getUser(username: string): Promise<User>; // USER_DNE
  removeUser(username: string): Promise<void>; // USER_DNE
  listUsers(): Promise<User[]>;
  hasUser(username: string): Promise<boolean>;

  // /dependencies
  addDependency(name: string, source?: 'MANUAL' | 'AUTO'): Promise<void>; // DP_EXISTS
  hasDependency(name: string): Promise<boolean>;
  removeDependency(name: string): Promise<void>; // DP_DNE
  listDependencies(): Promise<string[]>;

  // /logs
  getLog(incidentId: string): Promise<{ incident: Incident; ticketIds: string[]; entries: AuditEntry[] }>; // UUID_DNE
  logEvent(incidentId: string | undefined, eventType: string, payload: unknown): Promise<void>;
  getAuditLog(incidentId: string): Promise<AuditEntry[]>;
  verifyAuditChain(): Promise<{ ok: boolean; brokenAtSeq?: number }>;

  // /reset: wipes the current scope and restores its default teams and users
  reset(): Promise<void>;

  // test sessions (testing.ts)
  createSession(sessionId: string, clientIp?: string): Promise<number>; // new scope; UUID_EXISTS if the ID was used
  endSession(scope: number, report: unknown): Promise<void>;
  getSessionReport(sessionId: string): Promise<unknown>; // stored report of an ended session, else undefined
  endOpenSessions(): Promise<void>; // after a restart, the sessions still open can't continue
  purgeEndedSessions(endedBefore: Date): Promise<number>; // deletes their rows; returns how many
}
