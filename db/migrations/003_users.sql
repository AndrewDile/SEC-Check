-- Users, their teams, and where their notifications go

CREATE TABLE users (
  scope_id        INT UNSIGNED NOT NULL DEFAULT 0,
  username        VARCHAR(64) NOT NULL,
  display_name    VARCHAR(255),
  contact_channel VARCHAR(32) NOT NULL DEFAULT 'log',  -- a notification service channel
  contact_address VARCHAR(255),
  auth_hash       VARCHAR(255),  -- scrypt of the client's Auth_Hash; sign-in doesn't check it yet
  created_at      DATETIME(3) NOT NULL,
  PRIMARY KEY (scope_id, username)
);

CREATE TABLE team_members (
  scope_id  INT UNSIGNED NOT NULL DEFAULT 0,
  team_name VARCHAR(64) NOT NULL,
  username  VARCHAR(64) NOT NULL,
  added_at  DATETIME(3) NOT NULL,
  PRIMARY KEY (scope_id, team_name, username),
  FOREIGN KEY (scope_id, team_name) REFERENCES teams (scope_id, team_name),
  FOREIGN KEY (scope_id, username) REFERENCES users (scope_id, username)
);

-- Default users (the web app's settings.json); /reset and new test sessions restore these
INSERT INTO users (username, created_at) VALUES
  ('alice', UTC_TIMESTAMP(3)), ('bob', UTC_TIMESTAMP(3)), ('carol', UTC_TIMESTAMP(3)),
  ('dana', UTC_TIMESTAMP(3)), ('core-gateway', UTC_TIMESTAMP(3));
INSERT INTO team_members (team_name, username, added_at)
  SELECT t.team_name, m.username, UTC_TIMESTAMP(3) FROM teams t JOIN (
    SELECT 'CYBER1' team_name, 'alice' username UNION ALL SELECT 'CYBER2', 'bob' UNION ALL SELECT 'LEGAL', 'carol'
    UNION ALL SELECT 'LEGAL', 'dana' UNION ALL SELECT 'CYBER1', 'dana' UNION ALL SELECT 'LEGAL', 'core-gateway'
    UNION ALL SELECT 'CYBER1', 'core-gateway' UNION ALL SELECT 'CYBER2', 'core-gateway'
  ) m USING (team_name) WHERE t.scope_id = 0;
