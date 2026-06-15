CREATE TABLE IF NOT EXISTS chat_messages (
  message_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
  role text NOT NULL,
  content text NOT NULL,
  correlation_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created_at
  ON chat_messages(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_created_at
  ON chat_sessions(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_unreal_client_created_at
  ON chat_sessions(unreal_client_id, created_at DESC);

INSERT INTO schema_migrations(version)
VALUES ('002_chat_messages')
ON CONFLICT (version) DO NOTHING;
