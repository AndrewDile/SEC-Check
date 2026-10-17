// Draft: methods the Core API calls to read/write the database.
// Every method writes an audit_log entry (reads included, per REQ-02).

export type Materiality = 'MATERIAL' | 'IMMATERIAL' | 'UNDECIDED';
export type Severity = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNDECIDED' | 'RESOLVED';
export type Urgency = 'URGENT' | 'NOT_URGENT' | 'UNDECIDED' | 'RESOLVED';
export type ErrorType = 'UUID_EXISTS' | 'UUID_DNE' | 'INVALID_DATA' | 'DP_EXISTS' | 'DP_DNE' | 'TIMEOUT';

export class DbError extends Error {
  constructor(public type: ErrorType, message: string) { super(message); }
}

export interface Incident {
  incidentId: string;
  description: string;
  dependencyName?: string;
  materiality: Materiality;
  severity: Severity;
  urgency: Urgency;
  reportedAt: Date;
  // Set when the ingestion worker reported it; (source, externalId) is unique
  source?: string;
  externalId?: string;
  ingest?: unknown;          // the worker's payload, returned as-is on a repeat report
}

export interface Ticket {
  ticketId: string;          // strong ID: <incident>_<ticket>_<version>
  incidentId: string;
  ticketNumber: number;
  version: number;
  description: string;
  severity: Severity;
  urgency: Urgency;
  teams: string[];
  claimedBy?: string;
  reportedAt: Date;
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

export interface Database {
  // /incidents
  createIncident(incident: Omit<Incident, 'materiality' | 'severity' | 'urgency'> & Partial<Incident>): Promise<Incident>; // UUID_EXISTS
  editIncident(incidentId: string, changes: Partial<Omit<Incident, 'incidentId'>>): Promise<Incident>;                    // UUID_DNE
  getIncident(incidentId: string): Promise<Incident>;                                                                     // UUID_DNE
  listIncidents(): Promise<Incident[]>;
  findIncidentBySource(source: string, externalId: string): Promise<Incident | undefined>;                                // /ingest/incidents dedupe

  // /tickets
  createTicket(incidentId: string, ticket: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[]; reportedAt: Date }): Promise<Ticket>;
  editTicket(incidentId: string, ticketNumber: number, changes: { description: string; severity?: Severity; urgency?: Urgency; teams?: string[] }): Promise<Ticket>; // new version
  getTicket(incidentId: string, ticketNumber: number, version?: number): Promise<Ticket>; // latest version unless given
  listTickets(): Promise<Ticket[]>;                                        // latest version of every ticket, for the web app queue
  listTicketIds(incidentId: string): Promise<string[]>;                    // all strong IDs, for /logs

  // /notifier
  notifyTeams(incidentId: string, ticketNumber: number, teams: string[]): Promise<void>;
  claimTicket(incidentId: string, ticketNumber: number, team: string): Promise<void>; // INVALID_DATA if claimed by another team

  // teams (no contract endpoint yet)
  createTeam(name: string, responsibility?: string): Promise<void>;
  listTeams(): Promise<{ name: string; responsibility?: string }[]>;

  // /dependencies
  addDependency(name: string, source?: 'MANUAL' | 'AUTO'): Promise<void>; // DP_EXISTS
  hasDependency(name: string): Promise<boolean>;
  removeDependency(name: string): Promise<void>;                          // DP_DNE
  listDependencies(): Promise<string[]>;

  // /logs
  logEvent(incidentId: string | undefined, eventType: string, payload: unknown): Promise<void>; // e.g. notifier delivery results
  getAuditLog(incidentId: string): Promise<AuditEntry[]>;
  verifyAuditChain(): Promise<{ ok: boolean; brokenAtSeq?: number }>;

  // /reset (testing only): wipes all tables, restores default teams
  reset(): Promise<void>;
}
