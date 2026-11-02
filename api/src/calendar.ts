// Form 8-K Item 1.05 is due within four business days of the materiality determination (Final Rule p. 12).
// Business days skip weekends and the holidays in business_calendar, counted on the New York date.

export const FILING_BUSINESS_DAYS = 4;

export const newYorkDate = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(d);

export function addBusinessDays(start: string, days: number, holidays: Set<string>) {
  const d = new Date(`${start}T00:00:00Z`);
  while (days > 0) {
    d.setUTCDate(d.getUTCDate() + 1);
    if (d.getUTCDay() % 6 !== 0 && !holidays.has(d.toISOString().slice(0, 10))) days--;
  }
  return d.toISOString().slice(0, 10);
}
