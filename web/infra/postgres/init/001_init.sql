CREATE TABLE IF NOT EXISTS schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS greenhouses (
  greenhouse_id text PRIMARY KEY,
  name text NOT NULL,
  location text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS beds (
  bed_id integer PRIMARY KEY,
  greenhouse_id text NOT NULL REFERENCES greenhouses(greenhouse_id),
  zone text NOT NULL,
  crop text NOT NULL,
  growth_stage text NOT NULL,
  harvestable boolean NOT NULL DEFAULT false,
  robot_accessible boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS robots (
  robot_id text PRIMARY KEY,
  display_name text NOT NULL,
  status text NOT NULL,
  current_bed_id integer REFERENCES beds(bed_id),
  battery_percent integer NOT NULL CHECK (battery_percent BETWEEN 0 AND 100),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actuators (
  actuator_id text PRIMARY KEY,
  greenhouse_id text NOT NULL REFERENCES greenhouses(greenhouse_id),
  actuator_type text NOT NULL,
  status text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  session_id text PRIMARY KEY,
  user_id text,
  unreal_client_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS robot_commands (
  command_id text PRIMARY KEY,
  session_id text REFERENCES chat_sessions(session_id),
  command_name text NOT NULL,
  correlation_id text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS control_tasks (
  task_id text PRIMARY KEY,
  command_name text NOT NULL,
  target_type text NOT NULL,
  target_id text NOT NULL,
  correlation_id text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domain_events (
  event_id text PRIMARY KEY,
  event_type text NOT NULL,
  correlation_id text NOT NULL,
  session_id text,
  command_id text,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_robot_commands_correlation_id
  ON robot_commands(correlation_id);

CREATE INDEX IF NOT EXISTS idx_domain_events_correlation_id
  ON domain_events(correlation_id);

CREATE INDEX IF NOT EXISTS idx_domain_events_command_id
  ON domain_events(command_id);

INSERT INTO schema_migrations(version)
VALUES ('001_domain_schema')
ON CONFLICT (version) DO NOTHING;
