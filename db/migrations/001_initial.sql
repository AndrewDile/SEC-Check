-- Draft schema. All times UTC.

CREATE TABLE teams (
  team_name      VARCHAR(64) PRIMARY KEY,
  responsibility VARCHAR(500),
  created_at     DATETIME(3) NOT NULL
);

CREATE TABLE incidents (
  incident_id     VARCHAR(64) PRIMARY KEY,  -- no '_' (used in ticket IDs)
  description     VARCHAR(5000) NOT NULL,
  dependency_name VARCHAR(255),
  materiality     ENUM('MATERIAL','IMMATERIAL','UNDECIDED') NOT NULL DEFAULT 'UNDECIDED',
  severity        ENUM('HIGH','MEDIUM','LOW','UNDECIDED','RESOLVED') NOT NULL DEFAULT 'UNDECIDED',
  urgency         ENUM('URGENT','NOT_URGENT','UNDECIDED','RESOLVED') NOT NULL DEFAULT 'UNDECIDED',
  reported_at     DATETIME(3) NOT NULL,
  created_at      DATETIME(3) NOT NULL,
  updated_at      DATETIME(3) NOT NULL
);

-- Append-only: an edit inserts a new version. Strong ID = <incident>_<ticket>_<version>
CREATE TABLE ticket_versions (
  incident_id   VARCHAR(64) NOT NULL,
  ticket_number INT UNSIGNED NOT NULL,
  version       INT UNSIGNED NOT NULL,
  description   VARCHAR(5000) NOT NULL,
  severity      ENUM('HIGH','MEDIUM','LOW','UNDECIDED','RESOLVED') NOT NULL DEFAULT 'UNDECIDED',
  urgency       ENUM('URGENT','NOT_URGENT','UNDECIDED','RESOLVED') NOT NULL DEFAULT 'UNDECIDED',
  reported_at   DATETIME(3) NOT NULL,
  created_at    DATETIME(3) NOT NULL,
  PRIMARY KEY (incident_id, ticket_number, version),
  FOREIGN KEY (incident_id) REFERENCES incidents (incident_id)
);

CREATE TABLE ticket_version_teams (
  incident_id   VARCHAR(64) NOT NULL,
  ticket_number INT UNSIGNED NOT NULL,
  version       INT UNSIGNED NOT NULL,
  team_name     VARCHAR(64) NOT NULL,
  PRIMARY KEY (incident_id, ticket_number, version, team_name),
  FOREIGN KEY (incident_id, ticket_number, version) REFERENCES ticket_versions (incident_id, ticket_number, version),
  FOREIGN KEY (team_name) REFERENCES teams (team_name)
);

-- Claim history; current owner = latest row
CREATE TABLE ticket_claims (
  claim_id      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  incident_id   VARCHAR(64) NOT NULL,
  ticket_number INT UNSIGNED NOT NULL,
  team_name     VARCHAR(64) NOT NULL,
  claimed_at    DATETIME(3) NOT NULL,
  FOREIGN KEY (incident_id) REFERENCES incidents (incident_id),
  FOREIGN KEY (team_name) REFERENCES teams (team_name)
);

CREATE TABLE notifications (
  notification_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  incident_id     VARCHAR(64) NOT NULL,
  ticket_number   INT UNSIGNED NOT NULL,
  team_name       VARCHAR(64) NOT NULL,
  notified_at     DATETIME(3) NOT NULL,
  FOREIGN KEY (incident_id) REFERENCES incidents (incident_id),
  FOREIGN KEY (team_name) REFERENCES teams (team_name)
);

CREATE TABLE dependencies (
  dp_name    VARCHAR(255) PRIMARY KEY,
  source     ENUM('MANUAL','AUTO') NOT NULL DEFAULT 'MANUAL',
  created_at DATETIME(3) NOT NULL
);

-- Append-only, hash-chained: hash = SHA-256(prev_hash + row)
CREATE TABLE audit_log (
  seq          BIGINT UNSIGNED PRIMARY KEY,
  occurred_at  DATETIME(3) NOT NULL,
  incident_id  VARCHAR(64),
  event_type   VARCHAR(64) NOT NULL,
  actor        VARCHAR(128),
  payload_json MEDIUMTEXT NOT NULL,
  prev_hash    CHAR(64) NOT NULL,
  hash         CHAR(64) NOT NULL UNIQUE
);

-- Block edits to append-only tables (TRUNCATE for /reset still works)
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only';
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only';
CREATE TRIGGER ticket_versions_no_update BEFORE UPDATE ON ticket_versions FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_versions is append-only';
CREATE TRIGGER ticket_versions_no_delete BEFORE DELETE ON ticket_versions FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_versions is append-only';
CREATE TRIGGER ticket_version_teams_no_update BEFORE UPDATE ON ticket_version_teams FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_version_teams is append-only';
CREATE TRIGGER ticket_version_teams_no_delete BEFORE DELETE ON ticket_version_teams FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_version_teams is append-only';
CREATE TRIGGER ticket_claims_no_update BEFORE UPDATE ON ticket_claims FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_claims is append-only';
CREATE TRIGGER ticket_claims_no_delete BEFORE DELETE ON ticket_claims FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_claims is append-only';
