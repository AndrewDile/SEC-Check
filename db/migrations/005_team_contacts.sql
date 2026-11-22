-- Where a team is notified. Notices go to teams only; a user's Contact isn't used for them.

CREATE TABLE team_contacts (
  scope_id   INT UNSIGNED NOT NULL DEFAULT 0,
  contact_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  team_name  VARCHAR(64) NOT NULL,
  channel    VARCHAR(32) NOT NULL,    -- email, slack or ms_teams
  address    VARCHAR(1024) NOT NULL,  -- Teams Workflows URLs run to several hundred characters
  added_at   DATETIME(3) NOT NULL,
  PRIMARY KEY (contact_id),
  KEY team_contacts_team (scope_id, team_name),
  FOREIGN KEY (scope_id, team_name) REFERENCES teams (scope_id, team_name)
);
