import { describe, expect, it } from 'vitest';
import type { AuditEntry, Incident, Ticket } from '../src/db/api.js';
import { form8k } from '../src/form8k.js';

const incident: Incident = {
  incidentId: 'INC-1',
  description: 'Bucket exposed customer records.',
  materiality: 'MATERIAL',
  severity: 'HIGH',
  urgency: 'URGENT',
  reportedAt: new Date('2026-11-02T14:00:00Z'),
  materialAt: new Date('2026-11-03T15:00:00Z'),
  filingDeadline: '2026-11-09',
};

const ticket = (n: number, v: number, description: string, extra: Partial<Ticket> = {}): Ticket => ({
  ticketId: `INC-1_${n}_${v}`,
  incidentId: 'INC-1',
  ticketNumber: n,
  version: v,
  description,
  severity: 'UNDECIDED',
  urgency: 'UNDECIDED',
  teams: [],
  reportedAt: new Date(`2026-11-0${2 + n}T16:0${v}:00Z`),
  incident,
  ...extra,
});

const edit = (after: string, note?: string): AuditEntry => ({
  seq: 1,
  occurredAt: new Date(),
  incidentId: 'INC-1',
  eventType: 'INCIDENT_EDITED',
  payload: { after: { materiality: after }, ...(note && { note }) },
  hash: '',
});

describe('Form 8-K export', () => {
  it('arranges tickets and decisions by nature, scope and timing', () => {
    const tickets = [
      ticket(1, 1, 'INTAKE: incident created via manual intake by alice'),
      ticket(2, 1, 'Logs pulled.', { teams: ['CYBER1'], claimedBy: 'CYBER2' }),
      ticket(2, 2, 'Logs pulled; 40,000 rows read.', { teams: ['CYBER1', 'LEGAL'], claimedBy: 'CYBER2' }),
    ];
    const entries = [edit('IMMATERIAL', 'Early guess.'), edit('MATERIAL', 'Customer data left.'), edit('MATERIAL')];
    const v = form8k(incident, tickets, entries);

    expect(v.Item_1_05.Nature).toBe('Bucket exposed customer records.\n\nLogs pulled; 40,000 rows read.');
    expect(v.Item_1_05.Scope).toEqual({ Severity: 'HIGH', Teams_Involved: ['CYBER1', 'CYBER2', 'LEGAL'] });
    expect(v.Item_1_05.Material_Impact).toBe('Customer data left.');
    expect(v.Item_1_05.Timing.Determined_At).toBe('2026-11-03T15:00:00.000Z');
    expect(v.Item_1_05.Timing.Events.map((e) => e.Ticket_ID)).toEqual(['INC-1_1_1', 'INC-1_2_1', 'INC-1_2_2']);
    expect(v.Filing).toEqual({ Determined_At: '2026-11-03T15:00:00.000Z', Filing_Deadline: '2026-11-09' });
    expect(v.Source_Tickets).toEqual(['INC-1_1_1', 'INC-1_2_1', 'INC-1_2_2']);
  });

  it('cuts long event summaries', () => {
    const v = form8k(incident, [ticket(1, 1, 'x'.repeat(1000))], []);
    expect(v.Item_1_05.Timing.Events[0].Summary).toHaveLength(300);
  });
});
