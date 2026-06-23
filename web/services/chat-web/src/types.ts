export type MessageRole = "user" | "assistant" | "system";

export type ChatMessage = {
  message_id: string;
  session_id: string;
  role: MessageRole;
  content: string;
  correlation_id: string;
  created_at: string;
};

// Structured GraphRAG evidence carried on the `agent.retrieval` event payload (`graph`), used to
// render a relationship card for relational station/zone/capability/KPI questions.
export type GraphStation = {
  station_id: string | number | null;
  station_type: string | null;
  zone: string | number | null;
  capabilities: string[];
  task_ready: boolean | null;
  accessible: boolean | null;
  state: string | null;
  bottleneck_rate: number | null;
  bottleneck_run_id: string | null;
};

export type GraphEvidence = {
  zone: string | null;
  capability: string | null;
  path: string[];
  stations: GraphStation[];
  latest_bottleneck: {value: number; run_id: string} | null;
};

export type DomainEvent = {
  event_id: string;
  event_type: string;
  correlation_id: string;
  session_id: string;
  command_id?: string | null;
  occurred_at: string;
  payload: Record<string, unknown>;
};

export type ChatResponse = {
  session_id: string;
  correlation_id: string;
  message: ChatMessage;
  command_id?: string | null;
  status?: string | null;
  events: DomainEvent[];
};

export type SessionResponse = {
  session_id: string;
  user_id?: string | null;
  unreal_client_id?: string | null;
  created_at?: string | null;
};

export type SessionSummary = SessionResponse & {
  message_count: number;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  first_user_message_preview?: string | null;
};

export type SessionListResponse = {
  sessions: SessionSummary[];
};

export type SessionMessagesResponse = {
  session_id: string;
  messages: ChatMessage[];
};

export type OverlayZone = {
  id: string;
  name: string;
  subtitle: string;
  active: boolean;
};

export type UnrealZoneFocusResponse = {
  status: string;
  zone_id: string;
  unreal_client_id: string;
  command_id: string;
  api_path: string;
  issued_at: string;
};

export type UnrealViewport = {
  mode: string;
  stream_url: string;
  telemetry_sse_url: string;
  transport: string;
  telemetry_transport: string;
  generated_at: string;
};

export type ProcessTelemetry = {
  cell_id: string;
  throughput: number;
  active_agvs: number;
  avg_wait_time: number;
  collision_risk: number;
  uptime: number;
  measured_at: string;
};

export type OverlayMetric = {
  id: string;
  title: string;
  subtitle: string;
  value: number;
  unit: string;
  trend_percent: number;
  series: number[];
};

export type OverlayWorkload = {
  id: string;
  title: string;
  subtitle: string;
  value: number;
  unit: string;
  status: string;
  active: boolean;
};

export type OverlayDashboard = {
  cell_id: string;
  zones: OverlayZone[];
  metrics: OverlayMetric[];
  workloads: OverlayWorkload[];
  command_feed: string[];
  generated_at: string;
};

// Per-AGV telemetry node, written by UE5 → telemetry-collector → Firebase RTDB.
export type AgvTelemetry = {
  cell_id: string;
  agv_id: string;
  battery: number;
  speed: number;
  state: string;
  destination: string;
  carrying_load?: boolean;
  completed_tasks?: number;
  position?: {x: number; y: number; z: number};
  ts?: number;
};

// In-process HUD snapshot, streamed on the process telemetry frame from UE5 and rendered by
// the web overlay HUD (replaces the removed in-viewport UE5 HUD).
export type HudSnapshot = {
  running: boolean;
  paused: boolean;
  speed_multiplier: number;
  progress_percent: number;
  progress_basis?: "simulated_time" | "real_time" | string;
  sim_elapsed_seconds?: number;
  sim_target_duration_seconds?: number;
  tasks_completed: number;
  collisions: number;
  policy_id: string;
  recent_events: string[];
  verdict_summary: string;
  verdict_passed: boolean;
};

// Aggregate process snapshot node at /cells/{cell_id}/process.
export type ProcessSnapshot = {
  cell_id: string;
  running?: boolean;
  paused?: boolean;
  speed_multiplier?: number;
  throughput: number;
  active_agvs: number;
  avg_wait_time: number;
  collision_risk: number;
  uptime: number;
  progress_percent?: number;
  progress_basis?: "simulated_time" | "real_time" | string;
  sim_elapsed_seconds?: number;
  sim_target_duration_seconds?: number;
  ts?: number;
};

export type CameraSelectResponse = {
  status: string;
  agv_id: string;
  unreal_client_id: string;
  command_id: string;
  api_path: string;
  issued_at: string;
};

export type Simulation = {
  simulation_id: string;
  name: string;
  agv_count: number;
  speed_multiplier: number;
  workload_percent: number;
  policy_id: string;
  duration_seconds: number;
  bottleneck_threshold_sec: number;
  created_at: string;
  updated_at: string;
};

export type SimulationListResponse = {
  simulations: Simulation[];
};

export type SimulationRequest = Omit<Simulation, "simulation_id" | "created_at" | "updated_at">;

export type SimulationRun = {
  run_id: string;
  simulation_id: string;
  status: "created" | "starting" | "running" | "paused" | "stopped" | "completed" | "failed";
  ue_run_id?: string | null;
  speed_multiplier: number;
  started_at?: string | null;
  ended_at?: string | null;
  result_json?: Record<string, unknown> | null;
  kpis_json?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type RunListResponse = {
  runs: SimulationRun[];
};

export type RunResultResponse = {
  run: SimulationRun;
  live?: Record<string, unknown> | null;
};
