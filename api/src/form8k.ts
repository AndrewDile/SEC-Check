// Form 8-K Item 1.05 export (REQ-06): a MATERIAL incident's tickets and audit entries arranged by the item's
// nature, scope and timing. It helps prepare the filing; it doesn't complete or file it.
import type { AuditEntry, Incident, Ticket } from './db/api.js';

// The web app's tickets recording user actions (web_app/secheck_web/audit.py), not facts about the incident
const ACTION_TICKET = /^(INTAKE|EDIT|DECISION)(:| by )/;
const SUMMARY_CHARS = 300;

// tickets: every version, oldest first; entries: the incident's audit entries, oldest first
export function form8k(incident: Incident, tickets: Ticket[], entries: AuditEntry[]) {
  const latest = new Map(tickets.map((t) => [t.ticketNumber, t]));
  const teams = [...new Set(tickets.flatMap((t) => [...t.teams, ...(t.claimedBy ? [t.claimedBy] : [])]))];
  // The note of each edit to MATERIAL is its rationale
  const rationales = entries
    .filter((e) => e.eventType === 'INCIDENT_EDITED')
    .map((e) => e.payload as { after?: { materiality?: string }; note?: string })
    .filter((p) => p.after?.materiality === 'MATERIAL' && p.note?.trim())
    .map((p) => p.note);
  const determinedAt = incident.materialAt?.toISOString();
  return {
    Incident_ID: incident.incidentId,
    Status: '8-K View Assembled',
    Item_1_05: {
      Nature: [incident.description, ...[...latest.values()].map((t) => t.description)]
        .filter((d) => d.trim() && !ACTION_TICKET.test(d))
        .join('\n\n'),
      Scope: {
        Severity: incident.severity,
        ...(incident.dependencyName && { Dependency_Name: incident.dependencyName }),
        Teams_Involved: teams,
      },
      Timing: {
        Discovered_At: incident.reportedAt.toISOString(),
        ...(determinedAt && { Determined_At: determinedAt }),
        Events: tickets.map((t) => ({
          Ticket_ID: t.ticketId,
          Timestamp: t.reportedAt.toISOString(),
          Summary: t.description.slice(0, SUMMARY_CHARS),
        })),
      },
      Material_Impact: rationales.join('\n\n'),
    },
    Filing: {
      ...(determinedAt && { Determined_At: determinedAt }),
      Filing_Deadline: incident.filingDeadline ?? null, // YYYY-MM-DD
    },
    Source_Tickets: tickets.map((t) => t.ticketId),
  };
}
