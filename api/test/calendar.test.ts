import { describe, expect, it } from 'vitest';
import { addBusinessDays, newYorkDate } from '../src/calendar.js';

const holidays = new Set(['2026-07-03', '2026-11-26', '2026-12-25']);

describe('filing deadline calendar', () => {
  it('counts four business days after the determination, skipping weekends and holidays', () => {
    expect(addBusinessDays('2026-11-02', 4, holidays)).toBe('2026-11-06'); // Monday -> Friday
    expect(addBusinessDays('2026-11-06', 4, holidays)).toBe('2026-11-12'); // over a weekend
    expect(addBusinessDays('2026-11-25', 4, holidays)).toBe('2026-12-02'); // over Thanksgiving
    expect(addBusinessDays('2026-07-02', 4, holidays)).toBe('2026-07-09'); // over Independence Day (observed)
    expect(addBusinessDays('2026-11-07', 4, holidays)).toBe('2026-11-12'); // from a Saturday
  });

  it('uses the New York date', () => {
    expect(newYorkDate(new Date('2026-11-03T03:00:00Z'))).toBe('2026-11-02');
    expect(newYorkDate(new Date('2026-11-03T05:00:00Z'))).toBe('2026-11-03');
  });
});
