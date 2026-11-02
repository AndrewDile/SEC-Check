-- Form 8-K Item 1.05 filing deadline: 4 business days after the first MATERIAL determination

ALTER TABLE incidents
  ADD material_at DATETIME(3) AFTER urgency,   -- first MATERIAL determination; never reset
  ADD filing_deadline DATE AFTER material_at;  -- 4 business days after material_at (New York date)

-- Days the SEC is closed besides weekends (US federal holidays, as observed)
CREATE TABLE business_calendar (
  day  DATE PRIMARY KEY,
  name VARCHAR(64) NOT NULL
);
INSERT INTO business_calendar VALUES
  ('2026-01-01', 'New Year''s Day'), ('2026-01-19', 'Martin Luther King Jr. Day'), ('2026-02-16', 'Washington''s Birthday'),
  ('2026-05-25', 'Memorial Day'), ('2026-06-19', 'Juneteenth'), ('2026-07-03', 'Independence Day'),
  ('2026-09-07', 'Labor Day'), ('2026-10-12', 'Columbus Day'), ('2026-11-11', 'Veterans Day'),
  ('2026-11-26', 'Thanksgiving Day'), ('2026-12-25', 'Christmas Day'),
  ('2027-01-01', 'New Year''s Day'), ('2027-01-18', 'Martin Luther King Jr. Day'), ('2027-02-15', 'Washington''s Birthday'),
  ('2027-05-31', 'Memorial Day'), ('2027-06-18', 'Juneteenth'), ('2027-07-05', 'Independence Day'),
  ('2027-09-06', 'Labor Day'), ('2027-10-11', 'Columbus Day'), ('2027-11-11', 'Veterans Day'),
  ('2027-11-25', 'Thanksgiving Day'), ('2027-12-24', 'Christmas Day'), ('2027-12-31', 'New Year''s Day');
