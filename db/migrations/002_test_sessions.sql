-- Test session scopes: scope_id 0 is the real data; each cross-team test session gets its own scope (test_sessions).

CREATE TABLE test_sessions (
  scope_id    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id  VARCHAR(255) NOT NULL UNIQUE,
  client_ip   VARCHAR(64),
  started_at  DATETIME(3) NOT NULL,
  ended_at    DATETIME(3),
  purged_at   DATETIME(3),
  report_json JSON
);

ALTER TABLE ticket_versions DROP FOREIGN KEY ticket_versions_ibfk_1;
ALTER TABLE ticket_version_teams DROP FOREIGN KEY ticket_version_teams_ibfk_1, DROP FOREIGN KEY ticket_version_teams_ibfk_2;
ALTER TABLE ticket_claims DROP FOREIGN KEY ticket_claims_ibfk_1, DROP FOREIGN KEY ticket_claims_ibfk_2;
ALTER TABLE notifications DROP FOREIGN KEY notifications_ibfk_1, DROP FOREIGN KEY notifications_ibfk_2;

ALTER TABLE teams
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, DROP PRIMARY KEY, ADD PRIMARY KEY (scope_id, team_name);
ALTER TABLE incidents
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, DROP PRIMARY KEY, ADD PRIMARY KEY (scope_id, incident_id),
  DROP INDEX incidents_source, ADD UNIQUE KEY incidents_source (scope_id, source, external_id);
ALTER TABLE ticket_versions
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, DROP PRIMARY KEY,
  ADD PRIMARY KEY (scope_id, incident_id, ticket_number, version);
ALTER TABLE ticket_version_teams
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, DROP PRIMARY KEY,
  ADD PRIMARY KEY (scope_id, incident_id, ticket_number, version, team_name);
ALTER TABLE ticket_claims
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, ADD INDEX ticket_claims_ticket (scope_id, incident_id, ticket_number);
ALTER TABLE notifications
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, ADD INDEX notifications_ticket (scope_id, incident_id, ticket_number);
ALTER TABLE dependencies
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, DROP PRIMARY KEY, ADD PRIMARY KEY (scope_id, dp_name);
ALTER TABLE audit_log
  ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, DROP PRIMARY KEY, ADD PRIMARY KEY (scope_id, seq),
  ADD INDEX audit_log_incident (scope_id, incident_id, seq);
ALTER TABLE audit_head
  DROP PRIMARY KEY, DROP COLUMN id, ADD scope_id INT UNSIGNED NOT NULL DEFAULT 0 FIRST, ADD PRIMARY KEY (scope_id);

ALTER TABLE ticket_versions ADD FOREIGN KEY (scope_id, incident_id) REFERENCES incidents (scope_id, incident_id);
ALTER TABLE ticket_version_teams
  ADD FOREIGN KEY (scope_id, incident_id, ticket_number, version)
    REFERENCES ticket_versions (scope_id, incident_id, ticket_number, version),
  ADD FOREIGN KEY (scope_id, team_name) REFERENCES teams (scope_id, team_name);
ALTER TABLE ticket_claims
  ADD FOREIGN KEY (scope_id, incident_id) REFERENCES incidents (scope_id, incident_id),
  ADD FOREIGN KEY (scope_id, team_name) REFERENCES teams (scope_id, team_name);
ALTER TABLE notifications
  ADD FOREIGN KEY (scope_id, incident_id) REFERENCES incidents (scope_id, incident_id),
  ADD FOREIGN KEY (scope_id, team_name) REFERENCES teams (scope_id, team_name);

-- Deletes stay blocked unless the connection sets @seccheck_purge (/reset and expired test sessions)
DROP TRIGGER audit_log_no_delete;
DROP TRIGGER ticket_versions_no_delete;
DROP TRIGGER ticket_version_teams_no_delete;
DROP TRIGGER ticket_claims_no_delete;
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log FOR EACH ROW
  IF @seccheck_purge IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only'; END IF;
CREATE TRIGGER ticket_versions_no_delete BEFORE DELETE ON ticket_versions FOR EACH ROW
  IF @seccheck_purge IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_versions is append-only'; END IF;
CREATE TRIGGER ticket_version_teams_no_delete BEFORE DELETE ON ticket_version_teams FOR EACH ROW
  IF @seccheck_purge IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_version_teams is append-only'; END IF;
CREATE TRIGGER ticket_claims_no_delete BEFORE DELETE ON ticket_claims FOR EACH ROW
  IF @seccheck_purge IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ticket_claims is append-only'; END IF;
