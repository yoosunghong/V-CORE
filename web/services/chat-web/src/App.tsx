import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  config,
  createSession,
  createSimulation,
  deleteSimulation,
  deleteSession,
  duplicateSimulation,
  fetchLlmStatus,
  fetchOverlayDashboard,
  fetchRunResult,
  fetchUnrealViewport,
  fetchSessionMessages,
  listSimulationRuns,
  listSimulations,
  listSessions,
  openUnrealTelemetryStream,
  openSessionEvents,
  pauseRun,
  resumeRun,
  runSimulation,
  selectAgvCamera,
  sendMessage,
  setRunSpeed,
  stopRun,
  updateSimulation
} from "./api";
import type {LlmStatus} from "./api";
import type {
  AgvTelemetry,
  ChatMessage,
  DomainEvent,
  GraphEvidence,
  GraphStation,
  HudSnapshot,
  OverlayDashboard,
  OverlayMetric,
  ProcessSnapshot,
  ProcessTelemetry,
  SimulationRequest,
  SessionSummary,
  SimulationRun,
  Simulation,
  UnrealViewport
} from "./types";
import "./styles.css";

type ReportVerdict = {passed: boolean; passed_labels: string[]; failed_labels: string[]};
type ReportKpis = Record<string, number | number[]>;
type HeatmapCell = {
  index: number;
  x: number;
  y: number;
  value: number;
  intensity: number;
  avgAgvs: number;
  congestion: number;
  waitSeconds: number;
  avgAgvsLabel: "Average AGVs" | "AGV presence";
  waitLabel: "Waiting Time" | "Estimated Wait";
};

type TranscriptItem =
  | {id: string; kind: "message"; role: "user" | "assistant"; text: string; at: string}
  | {id: string; kind: "event"; eventType: string; text: string; at: string}
  | {id: string; kind: "report"; text: string; at: string; kpis: ReportKpis | null; verdict: ReportVerdict | null}
  | {id: string; kind: "graph"; evidence: GraphEvidence; at: string}
  | {id: string; kind: "plan"; text: string; index: number; total: number; at: string};

type ProgressStatus = {
  id: string;
  title: string;
  text: string;
  at: string;
};

type LogToast = {
  id: string;
  text: string;
  at: string;
};

const defaultSimulationDraft: SimulationRequest = {
  name: "Baseline AGV cell",
  agv_count: 3,
  speed_multiplier: 1,
  workload_percent: 100,
  policy_id: "POLICY_FIFO",
  duration_seconds: 600,
  bottleneck_threshold_sec: 10
};

const speedStops = [0.5, 1, 2, 4, 8];

// Event types that surface as ephemeral top-of-screen work logs (auto-dismiss after 5s).
const loggableEvents = new Set<string>([
  "llm.tool_call.proposed",
  "robot.command.requested",
  "robot.command.accepted",
  "robot.moving",
  "robot.working",
  "robot.command.completed",
  "robot.command.failed",
  "simulation.created",
  "simulation.run.updated",
  "agent.optimize.started",
  "agent.optimize.iteration",
  "agent.optimize.completed"
]);

// Events that imply UE5 is now driving a live simulation (chat-started runs have no
// frontend activeRun, so these make the UE viewport appear the moment the sim starts).
// simulation.created is included because it arrives in the HTTP response events list
// (unlike robot.command.* which only travel via the session WebSocket), ensuring the
// viewport mounts immediately even when the WS delivery races the HTTP response.
const simActiveEvents = new Set<string>([
  "robot.command.requested",
  "robot.command.accepted",
  "robot.moving",
  "robot.working",
  "simulation.created"
]);

type StoredChatState = {
  sessionId: string | null;
  items: TranscriptItem[];
};

const storageKey = "vp-chat-web-state";
const sessionTitlePrefix = "A Summary of AI's User Requirements Analysis";

const fallbackDashboard: OverlayDashboard = {
  cell_id: "VP-CELL-048-ALPHA",
  generated_at: new Date().toISOString(),
  zones: [
    {id: "zone-1", name: "ZONE 1", subtitle: "AGV cell - main view", active: true},
    {id: "zone-2", name: "ZONE 2", subtitle: "AGV cell - work", active: false},
    {id: "zone-3", name: "ZONE 3", subtitle: "AGV cell - unloading", active: false}
  ],
  metrics: [
    {id: "throughput", title: "Throughput", subtitle: "처리량", value: 68.2, unit: "/h", trend_percent: 2.1, series: [8, 9, 10, 24, 31, 36, 45, 52]},
    {id: "uptime", title: "Uptime", subtitle: "가동률", value: 97, unit: "%", trend_percent: 2.1, series: [18, 19, 21, 22, 24, 25, 27, 30]},
    {id: "avg-wait-time", title: "Avg Wait Time", subtitle: "평균 대기시간", value: 12, unit: "s", trend_percent: 2.1, series: [52, 51, 54, 55, 58, 56, 59, 61]},
    {id: "collision-risk", title: "Collision Risk", subtitle: "충돌 위험도", value: 0, unit: "/h", trend_percent: 2.1, series: [20, 21, 21, 22, 23, 22, 23, 24]},
    {id: "active-agvs", title: "Active AGVs", subtitle: "가동 AGV", value: 3, unit: "대", trend_percent: 2.1, series: [12, 20, 30, 42, 54, 68, 76, 87]}
  ],
  workloads: [],
  command_feed: []
};

const loopbackHosts = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"]);

function preferredStreamHost(): string {
  const host = window.location.hostname;
  if (!host || host === "localhost" || host === "0.0.0.0" || host === "::1" || host === "[::1]") {
    return "127.0.0.1";
  }
  return host;
}

function normalizeStreamUrl(streamUrl: string): string {
  if (!streamUrl) return "";
  try {
    const url = new URL(streamUrl, window.location.href);
    const isLoopback = loopbackHosts.has(url.hostname.toLowerCase());
    const isSameHostDiffPort =
      url.hostname === window.location.hostname &&
      url.port !== (window.location.port || "");
    if (isLoopback || isSameHostDiffPort) {
      const currentHost = preferredStreamHost();
      if (currentHost === "127.0.0.1") {
        // Local: replace hostname so direct port access still works
        url.hostname = currentHost;
        return url.toString();
      }
      // Proxied (ngrok etc): PS player + signalling WS are both at /ps/ via nginx.
      // 'ss' is the TextParameters.SignallingServerUrl key consumed by useUrlParams.
      const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const psUrl = new URL("/ps/", window.location.origin);
      psUrl.searchParams.set("ss", `${wsProto}//${window.location.host}/ps/`);
      return psUrl.toString();
    }
    return url.toString();
  } catch {
    return streamUrl;
  }
}

// Player flags forced on the embedded UE5 viewport so the stream connects and plays
// with zero operator interaction. Single source of truth — the iframe must never show
// a "click to start" connect overlay nor a play button:
//   AutoConnect      — skip the connect overlay and dial the signalling server immediately.
//   AutoPlayVideo    — start the video as soon as media arrives instead of a play button.
//   StartVideoMuted  — required for AutoPlayVideo to actually fire: UE runs with -AudioMixer,
//                      so the track carries audio, and browsers block autoplay of audible
//                      media without a user gesture. Muted video is exempt from that policy.
//   MaxReconnectAttempts — keep retrying if the signalling server/streamer is still booting.
//   MatchViewportRes — drive UE's render resolution to the iframe's exact size so the video
//                      fills the viewport instead of letterboxing (the black bars on all four
//                      sides appear when the streamer's aspect ratio differs from the player).
const pixelStreamingPlayerParams: Record<string, string> = {
  AutoConnect: "true",
  AutoPlayVideo: "true",
  StartVideoMuted: "true",
  MatchViewportRes: "true",
  MaxReconnectAttempts: "999"
};

function withPixelStreamingParams(streamUrl: string): string {
  const normalized = normalizeStreamUrl(streamUrl);
  if (!normalized) return "";
  try {
    const url = new URL(normalized, window.location.href);
    for (const [key, value] of Object.entries(pixelStreamingPlayerParams)) {
      url.searchParams.set(key, value);
    }
    return url.toString();
  } catch {
    const query = Object.entries(pixelStreamingPlayerParams)
      .map(([key, value]) => `${key}=${value}`)
      .join("&");
    return `${normalized}${normalized.includes("?") ? "&" : "?"}${query}`;
  }
}

const fallbackViewport: UnrealViewport = {
  mode: "mock",
  stream_url: `${window.location.protocol}//${preferredStreamHost()}:8880`,
  telemetry_sse_url: "/unreal/telemetry/stream",
  transport: "pixel-streaming-webrtc",
  telemetry_transport: "sse",
  generated_at: new Date().toISOString()
};

// Pause between revealing successive plan/event items so the agent's planning process streams
// into the chat step-by-step (one step "completing" at a time) rather than appearing all at once.
const PLAN_STEP_REVEAL_MS = 650;

const eventLabels: Record<string, string> = {
  "chat.message.received": "메시지 수신",
  "agent.plan.started": "실행 플랜",
  "agent.plan.completed": "플랜 확정",
  "llm.tool_call.proposed": "도구 판단",
  "process.telemetry.reported": "공정 텔레메트리",
  "robot.command.requested": "AGV 명령 요청",
  "robot.command.accepted": "AGV 명령 접수",
  "robot.moving": "AGV 이동",
  "robot.working": "스테이션 작업",
  "robot.command.completed": "작업 완료",
  "robot.command.failed": "작업 실패",
  "chat.report.generating": "보고서 생성",
  "chat.report.generated": "결과 보고",
  "unreal.zone.focus.requested": "Unreal 구역 전환",
  "simulation.created": "시뮬레이션 생성",
  "simulation.run.updated": "시뮬레이션 실행 변경",
  "agent.optimize.started": "최적화 탐색 시작",
  "agent.optimize.iteration": "최적화 반복",
  "agent.optimize.completed": "최적화 완료"
};

const simulationStatusLabels: Record<string, string> = {
  starting: "시작 중",
  running: "실행 중",
  paused: "일시정지",
  stopped: "정지",
  completed: "완료",
  failed: "실패"
};

function loadStoredState(): StoredChatState {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return {sessionId: null, items: []};
    const parsed = JSON.parse(raw) as StoredChatState;
    return {
      sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : null,
      items: Array.isArray(parsed.items) ? parsed.items : []
    };
  } catch {
    return {sessionId: null, items: []};
  }
}

function payloadValue(event: DomainEvent, key: string): unknown {
  return event.payload[key];
}

function eventText(event: DomainEvent): string {
  if (event.event_type === "chat.report.generated" && typeof payloadValue(event, "content") === "string") {
    return payloadValue(event, "content") as string;
  }

  if (event.event_type === "agent.plan.started") {
    const steps = payloadValue(event, "steps");
    const stepCount = Array.isArray(steps) ? steps.length : 0;
    return stepCount > 0 ? `${stepCount}단계 실행 계획을 준비했습니다.` : "실행 계획을 준비했습니다.";
  }

  if (event.event_type === "process.telemetry.reported") {
    return "최신 가상 공정 텔레메트리를 확인했습니다.";
  }

  if (event.event_type === "simulation.created") {
    const name = payloadValue(event, "name");
    const runId = payloadValue(event, "run_id");
    const shortId = typeof runId === "string" ? runId.slice(-8) : null;
    const label = typeof name === "string" ? `"${name}"` : "시뮬레이션";
    return shortId
      ? `${label} 실행 시작 · 실행 ID: ${shortId}`
      : typeof name === "string"
      ? `시뮬레이션 "${name}"을(를) 목록에 추가하고 실행을 시작했습니다.`
      : "챗봇 시뮬레이션를 목록에 추가하고 실행을 시작했습니다.";
  }

  if (event.event_type === "simulation.run.updated") {
    const statusValue = payloadValue(event, "status");
    const statusLabel = typeof statusValue === "string" ? simulationStatusLabels[statusValue] ?? statusValue : "변경";
    return `시뮬레이션 실행 상태를 ${statusLabel}(으)로 갱신했습니다.`;
  }

  const stationId = payloadValue(event, "station_id") ?? payloadValue(event, "target_station_id");
  const target = stationId ? `${String(stationId)}번 스테이션` : "디지털 트윈";
  switch (event.event_type) {
    case "chat.message.received":
      return "사용자 메시지를 수신하고 세션 스트림을 동기화했습니다.";
    case "agent.plan.completed":
      return "실행 계획을 확정하고 다음 단계를 준비합니다.";
    case "llm.tool_call.proposed":
      return `${target}에 사용할 도구 계약을 선택했습니다.`;
    case "robot.command.requested":
      return `${target} 작업을 UE5 공정에 전송했습니다.`;
    case "robot.command.accepted":
      return `${target} AGV 명령이 접수되었습니다.`;
    case "robot.moving":
      return `AGV가 ${target}으로 이동 중입니다.`;
    case "robot.working":
      return `AGV가 ${target}에서 작업 중입니다.`;
    case "robot.command.completed":
      return `${target} AGV 작업이 완료되었습니다.`;
    case "robot.command.failed":
      return `${target} AGV 작업이 실패했습니다. 복구 옵션을 확인합니다.`;
    default:
      return eventLabels[event.event_type] ?? event.event_type;
  }
}

function toAssistantItem(message: ChatMessage): TranscriptItem {
  return {
    id: message.message_id,
    kind: "message",
    role: message.role === "user" ? "user" : "assistant",
    text: message.content,
    at: message.created_at
  };
}

function toTranscriptItem(event: DomainEvent): TranscriptItem {
  if (event.event_type === "agent.plan.step") {
    const text = payloadValue(event, "text");
    const index = payloadValue(event, "index");
    const total = payloadValue(event, "total");
    return {
      id: event.event_id,
      kind: "plan",
      text: typeof text === "string" ? text : "Executing plan step.",
      index: typeof index === "number" ? index : 1,
      total: typeof total === "number" ? total : 1,
      at: event.occurred_at
    };
  }

  return {
    id: event.event_id,
    kind: "event",
    eventType: event.event_type,
    text: eventText(event),
    at: event.occurred_at
  };
}

function progressStatusFromEvent(event: DomainEvent): ProgressStatus | null {
  if (event.event_type === "chat.report.generated" || event.event_type === "unreal.zone.focus.requested") {
    return null;
  }

  if (event.event_type === "chat.report.generating") {
    return {
      id: event.event_id,
      title: "보고서 생성 중",
      text: "시뮬레이션이 종료되었습니다. 결과 보고서를 생성하고 있습니다.",
      at: event.occurred_at
    };
  }

  if (event.event_type === "agent.plan.step") {
    const text = payloadValue(event, "text");
    const index = payloadValue(event, "index");
    const total = payloadValue(event, "total");
    const prefix =
      typeof index === "number" && typeof total === "number" ? `${index}/${total}단계` : "계획 단계";
    return {
      id: event.event_id,
      title: "실행 플랜 수립",
      text: `${prefix}: ${typeof text === "string" ? text : "계획 단계를 실행 중입니다."}`,
      at: event.occurred_at
    };
  }

  const progressTitles: Record<string, string> = {
    "chat.message.received": "메시지 수신",
    "agent.plan.started": "실행 플랜 수립",
    "agent.plan.completed": "플랜 확정",
    "llm.tool_call.proposed": "도구 호출 준비",
    "process.telemetry.reported": "공정 상태 확인",
    "robot.command.requested": "AGV 명령 전송",
    "robot.command.accepted": "AGV 명령 접수",
    "robot.moving": "AGV 이동 중",
    "robot.working": "스테이션 작업 중",
    "robot.command.completed": "작업 완료 확인",
    "robot.command.failed": "작업 실패 확인"
  };

  return {
    id: event.event_id,
    title: progressTitles[event.event_type] ?? eventLabels[event.event_type] ?? event.event_type,
    text: eventText(event),
    at: event.occurred_at
  };
}

function shouldAppendEventToTranscript(event: DomainEvent): boolean {
  return (
    event.event_type === "agent.plan.started" ||
    event.event_type === "agent.plan.step" ||
    event.event_type === "agent.plan.completed" ||
    event.event_type === "unreal.zone.focus.requested"
  );
}

function formatMetricValue(metric: OverlayMetric): string {
  if (metric.unit === "°C") return metric.value.toFixed(1);
  return metric.value.toFixed(2);
}

function Sparkline({series}: {series: number[]}) {
  const points = series.length > 0 ? series : [0, 0];
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = Math.max(max - min, 1);
  const path = points
    .map((value, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 100;
      const y = 48 - ((value - min) / range) * 36;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg className="sparkline" viewBox="0 0 100 52" preserveAspectRatio="none" aria-hidden="true">
      <path className="sparkFill" d={`${path} L 100 52 L 0 52 Z`} />
      <path className="sparkPath" d={path} />
    </svg>
  );
}

function MetricCard({
  metric,
  collapsed,
  onToggle
}: {
  metric: OverlayMetric;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <article className="metricCard" data-collapsed={collapsed}>
      <button
        type="button"
        className="cardCollapse"
        aria-expanded={!collapsed}
        aria-label={collapsed ? `${metric.title} 펼치기` : `${metric.title} 접기`}
        onClick={onToggle}
      >
        {collapsed ? "+" : "–"}
      </button>
      <div className="metricKicker">{metric.subtitle}</div>
      <h2>{metric.title}</h2>
      {!collapsed ? (
        <>
          <div className="metricValue">
            <strong>{formatMetricValue(metric)}</strong>
            <span>{metric.unit}</span>
            <em>+{metric.trend_percent.toFixed(1)}%</em>
          </div>
          <Sparkline series={metric.series} />
        </>
      ) : null}
    </article>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function formatDateTimeKst(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date);
}

function normalizeMessageText(text: string): string {
  let normalized = text.trim();
  if (!normalized.includes("\n") && /\s-\s/.test(normalized)) {
    normalized = normalized.replace(/\s+-\s+/g, "\n- ");
  }
  return normalized.replace(/(\.)\s+(원하시면|필요하시면)/g, "$1\n\n$2");
}

function renderInline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`/g;
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1] !== undefined) parts.push(<strong key={i++}>{m[1]}</strong>);
    else if (m[2] !== undefined) parts.push(<em key={i++}>{m[2]}</em>);
    else if (m[3] !== undefined) parts.push(<code key={i++}>{m[3]}</code>);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function MessageContent({text}: {text: string}) {
  const lines = normalizeMessageText(text)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line, index, source) => line.length > 0 || source[index - 1]?.length);
  const nodes: ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = () => {
    if (listItems.length === 0) return;
    nodes.push(
      <ul className="messageList" key={`list-${nodes.length}`}>
        {listItems.map((item, index) => (
          <li key={`${item}-${index}`}>{renderInline(item)}</li>
        ))}
      </ul>
    );
    listItems = [];
  };

  lines.forEach((line) => {
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      listItems.push(bullet[1]);
      return;
    }

    flushList();
    nodes.push(<p key={`p-${nodes.length}`}>{renderInline(line)}</p>);
  });
  flushList();

  return <div className="messageContent">{nodes}</div>;
}

// Highlight terms that read as a pass/warn verdict so the report header reflects the outcome
// when no structured verdict payload is attached (e.g. station-task completion reports).
const reportPassHints = ["통과", "정상", "달성", "충족", "pass", "passed", "accept", "정상 가동"];
const reportWarnHints = ["미달", "초과", "실패", "위반", "병목", "충돌", "fail", "bottleneck", "collision", "warn"];

function reportTextTone(text: string): "pass" | "warn" | "info" {
  const lower = text.toLowerCase();
  if (reportWarnHints.some((hint) => lower.includes(hint))) return "warn";
  if (reportPassHints.some((hint) => lower.includes(hint))) return "pass";
  return "info";
}

const heatmapKeys = new Set(["heatmap_grid", "heatmap_res_x", "heatmap_res_y"]);
const heatmapArrayKeys = new Set([
  "heatmap_grid",
  "heatmap_congestion_grid",
  "heatmap_avg_agvs_grid",
  "heatmap_wait_time_grid",
  "heatmap_wait_seconds_grid"
]);

function parseReportKpis(raw: unknown): ReportKpis | null {
  if (!raw || typeof raw !== "object") return null;
  const entries = Object.entries(raw as Record<string, unknown>).filter(([key, value]) => {
    if (typeof value === "number" && Number.isFinite(value)) return true;
    return heatmapArrayKeys.has(key) && Array.isArray(value) && value.every((item) => typeof item === "number");
  }) as [string, number | number[]][];
  return entries.length > 0 ? Object.fromEntries(entries) : null;
}

function parseReportVerdict(raw: unknown): ReportVerdict | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const toLabels = (input: unknown): string[] =>
    Array.isArray(input) ? input.map((item) => String(item)) : [];
  const passed_labels = toLabels(value.passed_labels);
  const failed_labels = toLabels(value.failed_labels);
  if (typeof value.passed !== "boolean" && passed_labels.length === 0 && failed_labels.length === 0) {
    return null;
  }
  return {passed: value.passed === true, passed_labels, failed_labels};
}

function numericGrid(kpis: ReportKpis, key: string): number[] | null {
  const raw = kpis[key];
  return Array.isArray(raw) ? raw : null;
}

function numericKpi(kpis: ReportKpis, key: string): number | null {
  const raw = kpis[key];
  return typeof raw === "number" ? raw : null;
}

function HeatmapGrid({kpis}: {kpis: ReportKpis}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoveredCell, setHoveredCell] = useState<HeatmapCell | null>(null);

  const grid = useMemo(() => {
    const raw = (kpis as Record<string, unknown>).heatmap_grid;
    return Array.isArray(raw) ? (raw as number[]) : null;
  }, [kpis]);

  const resX = typeof kpis.heatmap_res_x === "number" ? kpis.heatmap_res_x : 24;
  const resY = typeof kpis.heatmap_res_y === "number" ? kpis.heatmap_res_y : 24;

  useEffect(() => {
    if (!grid || grid.length === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const cellW = canvas.width / resX;
    const cellH = canvas.height / resY;
    const peak = Math.max(...grid, 0.001);

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (let i = 0; i < grid.length; i++) {
      const t = Math.min(grid[i] / peak, 1);
      if (t < 0.01) continue;
      const cx = i % resX;
      const cy = Math.floor(i / resX);
      // cool (blue) → warm (orange-red) ramp
      const r = Math.round(30 + t * 225);
      const g = Math.round(144 - t * 120);
      const b = Math.round(255 - t * 255);
      ctx.fillStyle = `rgba(${r},${g},${b},${0.15 + t * 0.75})`;
      ctx.fillRect(cx * cellW, cy * cellH, cellW, cellH);
    }
  }, [grid, resX, resY]);

  if (!grid) return null;

  const peak = Math.max(...grid, 0.001);
  const avgWaitTime = numericKpi(kpis, "avg_wait_time") ?? 0;
  const congestionGrid = numericGrid(kpis, "heatmap_congestion_grid");
  const avgAgvsGrid = numericGrid(kpis, "heatmap_avg_agvs_grid");
  const waitGrid = numericGrid(kpis, "heatmap_wait_time_grid") ?? numericGrid(kpis, "heatmap_wait_seconds_grid");
  const cellCount = Math.max(grid.length, resX * resY);
  const cells = Array.from({length: cellCount}, (_, index): HeatmapCell => {
    const value = grid[index] ?? 0;
    const intensity = Math.min(Math.max(value / peak, 0), 1);
    const congestion = congestionGrid?.[index] ?? intensity;
    return {
      index,
      x: index % resX,
      y: Math.floor(index / resX),
      value,
      intensity,
      avgAgvs: avgAgvsGrid?.[index] ?? value,
      congestion,
      waitSeconds: waitGrid?.[index] ?? avgWaitTime * intensity,
      avgAgvsLabel: avgAgvsGrid ? "Average AGVs" : "AGV presence",
      waitLabel: waitGrid ? "Waiting Time" : "Estimated Wait"
    };
  });
  const calloutCell = hoveredCell ?? cells[0];
  const cellStyle = (cell: HeatmapCell): React.CSSProperties => {
    const r = Math.round(30 + cell.intensity * 225);
    const g = Math.round(144 - cell.intensity * 120);
    const b = Math.round(255 - cell.intensity * 255);
    return {backgroundColor: `rgba(${r}, ${g}, ${b}, ${0.18 + cell.intensity * 0.74})`};
  };

  return (
    <div className="reportHeatmap">
      <span className="reportHeatmapLabel">혼잡도 히트맵 · Congestion Heatmap</span>
      <div
        className="reportHeatmapGrid"
        style={{gridTemplateColumns: `repeat(${resX}, minmax(0, 1fr))`}}
        onMouseLeave={() => setHoveredCell(null)}
      >
        {cells.map((cell) => (
          <button
            type="button"
            className="reportHeatmapCell"
            key={cell.index}
            aria-label={`Cell ${cell.x + 1}, ${cell.y + 1}`}
            style={cellStyle(cell)}
            onMouseEnter={() => setHoveredCell(cell)}
            onFocus={() => setHoveredCell(cell)}
            onBlur={() => setHoveredCell(null)}
          />
        ))}
      </div>
      <div className="reportHeatmapCallout" data-active={hoveredCell !== null} role="status" aria-live="polite">
        <strong>
          Cell {calloutCell.x + 1}, {calloutCell.y + 1}
        </strong>
        <dl>
          <div>
            <dt>{calloutCell.avgAgvsLabel}</dt>
            <dd>{calloutCell.avgAgvs.toFixed(2)}</dd>
          </div>
          <div>
            <dt>Congestion Level</dt>
            <dd>{(calloutCell.congestion * 100).toFixed(0)}%</dd>
          </div>
          <div>
            <dt>{calloutCell.waitLabel}</dt>
            <dd>{calloutCell.waitSeconds.toFixed(1)}s</dd>
          </div>
        </dl>
      </div>
      <div className="reportHeatmapLegend">
        <span>Low</span>
        <div className="reportHeatmapGradient" />
        <span>High</span>
      </div>
    </div>
  );
}

type EvalLine = {text: string; tone: "good" | "warn" | "bad" | "info"};

type AiEvaluation = {grade: string; gradeTone: "good" | "warn" | "bad"; headline: string; lines: EvalLine[]};

// Derive congestion characteristics from the UE5 heatmap grid so the evaluation can describe
// *where* and *how* concentrated the congestion is, not just the raw KPI numbers.
function heatmapStats(
  kpis: ReportKpis
): {concentration: number; hotFraction: number; hotspot: string} | null {
  const grid = numericGrid(kpis, "heatmap_grid");
  if (!grid || grid.length === 0) return null;
  const peak = Math.max(...grid);
  if (peak <= 0) return null;
  const resX = numericKpi(kpis, "heatmap_res_x") ?? 24;
  const resY = numericKpi(kpis, "heatmap_res_y") ?? Math.round(grid.length / resX);
  const mean = grid.reduce((acc, value) => acc + value, 0) / grid.length;
  const concentration = mean > 0 ? peak / mean : 0;
  const hotFraction = grid.filter((value) => value >= peak * 0.6).length / grid.length;
  const peakIndex = grid.indexOf(peak);
  const cx = peakIndex % resX;
  const cy = Math.floor(peakIndex / resX);
  const horizontal = cx < resX / 2 ? "좌측" : "우측";
  const vertical = cy < resY / 2 ? "상단" : "하단";
  return {concentration, hotFraction, hotspot: `${vertical} ${horizontal}`};
}

// Turn the final run KPIs + acceptance verdict into a qualitative AI assessment (grade,
// headline, per-metric notes incl. heatmap analysis) so the report reads as an evaluation,
// not just a number dump. Pure/deterministic so it renders identically in chat and studio.
function buildAiEvaluation(kpis: ReportKpis, verdict: ReportVerdict | null): AiEvaluation | null {
  const lines: EvalLine[] = [];
  let score = 0;
  let count = 0;
  const rate = (good: boolean, warn: boolean) => {
    count += 1;
    score += good ? 2 : warn ? 1 : 0;
    return good ? "good" : warn ? "warn" : "bad";
  };

  const heat = heatmapStats(kpis);
  if (heat) {
    const concentrated = heat.concentration >= 3.5 && heat.hotFraction <= 0.15;
    lines.push({
      text: concentrated
        ? `혼잡 히트맵: 혼잡이 ${heat.hotspot} 구역에 집중되어 국부적 병목 위험이 있습니다 (집중도 ${heat.concentration.toFixed(1)}배).`
        : `혼잡 히트맵: 혼잡도가 셀 전반에 비교적 고르게 분산되어 있습니다 (집중도 ${heat.concentration.toFixed(1)}배, 최다 ${heat.hotspot}).`,
      tone: concentrated ? "warn" : "good"
    });
  }

  const throughput = numericKpi(kpis, "throughput");
  if (throughput !== null) {
    const v = throughput;
    const tone = rate(v >= 60, v >= 40);
    lines.push({
      text: `처리량 ${v.toFixed(1)}/h — ${tone === "good" ? "목표 처리량을 충분히 달성했습니다." : tone === "warn" ? "목표에 근접하나 개선 여지가 있습니다." : "목표를 크게 밑돌아 라인 효율 점검이 필요합니다."}`,
      tone
    });
  }
  const avgWait = numericKpi(kpis, "avg_wait_time");
  if (avgWait !== null) {
    const v = avgWait;
    const tone = rate(v <= 10, v <= 20);
    lines.push({
      text: `평균 대기시간 ${v.toFixed(1)}s — ${tone === "good" ? "교차로 대기가 짧아 흐름이 원활합니다." : tone === "warn" ? "대기시간이 다소 길어 일부 정체가 보입니다." : "대기시간이 길어 병목이 발생하고 있습니다."}`,
      tone
    });
  }
  const collisionRisk = numericKpi(kpis, "collision_risk");
  if (collisionRisk !== null) {
    const v = collisionRisk;
    const tone = rate(v <= 0.5, v <= 1.5);
    lines.push({
      text: `충돌 위험도 ${v.toFixed(2)}/h — ${tone === "good" ? "충돌 위험이 낮아 안전성이 확보되었습니다." : tone === "warn" ? "간헐적 충돌 위험이 관측됩니다." : "충돌 위험이 높아 경로·우선순위 정책 재검토가 필요합니다."}`,
      tone
    });
  }
  const uptime = numericKpi(kpis, "uptime");
  if (uptime !== null) {
    const v = uptime;
    const tone = rate(v >= 0.95, v >= 0.85);
    lines.push({
      text: `가동률 ${(v * 100).toFixed(0)}% — ${tone === "good" ? "설비 가동률이 우수합니다." : tone === "warn" ? "양호하나 유휴 구간이 존재합니다." : "가동률이 낮아 유휴·정지 원인 분석이 필요합니다."}`,
      tone
    });
  }

  if (lines.length === 0) return null;

  const ratio = count > 0 ? score / (count * 2) : 0.5;
  const {grade, gradeTone} =
    ratio >= 0.8
      ? {grade: "A · 우수", gradeTone: "good" as const}
      : ratio >= 0.55
        ? {grade: "B · 양호", gradeTone: "warn" as const}
        : {grade: "C · 주의", gradeTone: "bad" as const};

  const headline = verdict
    ? verdict.passed
      ? "수용 기준을 통과했으며 핵심 KPI가 안정적으로 유지되었습니다."
      : "수용 기준 미달 항목이 있어 아래 지표를 우선 개선해야 합니다."
    : gradeTone === "good"
      ? "전반적으로 안정적인 운영 성능을 보였습니다."
      : gradeTone === "warn"
        ? "운영은 가능하나 일부 지표에서 개선이 필요합니다."
        : "여러 지표에서 위험이 감지되어 정책 재검토를 권장합니다.";

  return {grade, gradeTone, headline, lines};
}

function AiEvaluationCard({kpis, verdict}: {kpis: ReportKpis; verdict: ReportVerdict | null}) {
  const evaluation = useMemo(() => buildAiEvaluation(kpis, verdict), [kpis, verdict]);
  if (!evaluation) return null;
  return (
    <div className="reportEval" data-grade={evaluation.gradeTone}>
      <div className="reportEvalHead">
        <span className="reportEvalKicker">AI 종합 평가 · Overall Assessment</span>
        <span className="reportEvalGrade" data-grade={evaluation.gradeTone}>{evaluation.grade}</span>
      </div>
      <p className="reportEvalHeadline">{evaluation.headline}</p>
      <ul className="reportEvalList">
        {evaluation.lines.map((line, index) => (
          <li key={index} data-tone={line.tone}>
            {line.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportVerdictBanner({verdict, tone}: {verdict: ReportVerdict; tone: string}) {
  return (
    <div className="reportVerdictBanner" data-tone={tone}>
      <strong>{verdict.passed ? "합격 · ACCEPTANCE PASS" : "검토 필요 · ACCEPTANCE FAIL"}</strong>
      <span>
        통과 {verdict.passed_labels.length} · 미달 {verdict.failed_labels.length}
      </span>
    </div>
  );
}

// Display metadata for the KPI keys UE5 reports in the final run KPIs payload.
const reportKpiMeta: Record<string, {title: string; unit: string; format: (value: number) => string}> = {
  throughput: {title: "Throughput", unit: "/h", format: (v) => v.toFixed(1)},
  avg_wait_time: {title: "Avg Wait Time", unit: "s", format: (v) => v.toFixed(1)},
  collision_risk: {title: "Collision Risk", unit: "/h", format: (v) => v.toFixed(2)},
  uptime: {title: "Uptime", unit: "%", format: (v) => (v * 100).toFixed(0)}
};

function ReportKpiGrid({kpis}: {kpis: ReportKpis}) {
  const ordered = Object.keys(reportKpiMeta).filter((key) => key in kpis);
  const extras = Object.keys(kpis).filter((key) => !(key in reportKpiMeta) && !heatmapKeys.has(key) && typeof kpis[key] === "number");
  const keys = [...ordered, ...extras];
  if (keys.length === 0) return null;
  return (
    <div className="reportKpiGrid">
      {keys.map((key) => {
        const meta = reportKpiMeta[key];
        const value = numericKpi(kpis, key);
        if (value === null) return null;
        const display = meta ? meta.format(value) : value.toFixed(2);
        return (
          <div className="reportKpiCard" key={key}>
            <span className="reportKpiTitle">{meta?.title ?? key}</span>
            <span className="reportKpiValue">
              <strong>{display}</strong>
              {meta?.unit ? <em>{meta.unit}</em> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ReportVerdictChips({verdict}: {verdict: ReportVerdict}) {
  if (verdict.passed_labels.length === 0 && verdict.failed_labels.length === 0) return null;
  return (
    <div className="reportVerdictChips">
      {verdict.passed_labels.map((label) => (
        <span className="reportChip" data-tone="pass" key={`pass-${label}`}>
          <span aria-hidden="true">✓</span>
          {label}
        </span>
      ))}
      {verdict.failed_labels.map((label) => (
        <span className="reportChip" data-tone="fail" key={`fail-${label}`}>
          <span aria-hidden="true">✕</span>
          {label}
        </span>
      ))}
    </div>
  );
}

// Final simulation report, rendered as a prominent card instead of a plain chat bubble so the
// post-run verdict and KPI breakdown stand out from the conversational stream.
function ReportCard({
  text,
  at,
  kpis,
  verdict
}: {
  text: string;
  at: string;
  kpis: ReportKpis | null;
  verdict: ReportVerdict | null;
}) {
  const tone = verdict ? (verdict.passed ? "pass" : "warn") : reportTextTone(text);
  const toneLabel = verdict ? (verdict.passed ? "PASS" : "FAIL") : tone === "pass" ? "PASS" : tone === "warn" ? "REVIEW" : "RESULT";
  return (
    <article className="reportCard" data-tone={tone}>
      <header className="reportCardHead">
        <span className="reportCardIcon" aria-hidden="true">📊</span>
        <div>
          <strong>시뮬레이션 결과 보고서</strong>
          <span>Virtual Process · Simulation Report</span>
        </div>
        <span className="reportCardBadge" data-tone={tone}>{toneLabel}</span>
      </header>
      {verdict ? <ReportVerdictBanner verdict={verdict} tone={tone} /> : null}
      {verdict ? <ReportVerdictChips verdict={verdict} /> : null}
      {kpis ? <ReportKpiGrid kpis={kpis} /> : null}
      {kpis ? <HeatmapGrid kpis={kpis} /> : null}
      {kpis ? <AiEvaluationCard kpis={kpis} verdict={verdict} /> : null}
      <div className="reportCardBody">
        <MessageContent text={text} />
      </div>
      <time>{formatTime(at)}</time>
    </article>
  );
}

// Parse the structured GraphRAG evidence off an `agent.retrieval` event. Returns null for vector
// (non-relational) hits, which carry no `graph` payload and stay as plain text.
function graphEvidenceFromEvent(event: DomainEvent): GraphEvidence | null {
  const graph = payloadValue(event, "graph");
  if (!graph || typeof graph !== "object") return null;
  const raw = graph as Record<string, unknown>;
  const stations = Array.isArray(raw.stations) ? (raw.stations as GraphStation[]) : [];
  if (stations.length === 0) return null;
  const path = Array.isArray(raw.path) ? (raw.path as string[]) : [];
  const latest = raw.latest_bottleneck;
  return {
    zone: typeof raw.zone === "string" ? raw.zone : raw.zone == null ? null : String(raw.zone),
    capability: typeof raw.capability === "string" ? raw.capability : null,
    path,
    stations,
    latest_bottleneck:
      latest && typeof latest === "object"
        ? (latest as {value: number; run_id: string})
        : null
  };
}

function formatBottleneck(value: number | null): string {
  return value == null ? "—" : `${value}%`;
}

// Relational (GraphRAG) answer rendered as an evidence card: the traversed graph path as a chain
// of chips, then the matched stations with capabilities and their last bottleneck_rate.
function GraphRagCard({evidence, at}: {evidence: GraphEvidence; at: string}) {
  const {zone, capability, path, stations, latest_bottleneck} = evidence;
  const scopeParts = [
    zone ? `Zone ${zone}` : "전체 셀",
    capability ? `· ${capability}` : ""
  ].filter(Boolean);
  return (
    <article className="graphCard">
      <header className="graphCardHead">
        <span className="graphCardIcon" aria-hidden="true">🕸️</span>
        <div>
          <strong>그래프 지식 근거</strong>
          <span>GraphRAG · Relationship Evidence</span>
        </div>
        <span className="graphCardScope">{scopeParts.join(" ")}</span>
      </header>
      {path.length > 0 ? (
        <div className="graphPath" aria-label="graph traversal path">
          {path.map((node, index) => (
            <span className="graphPathStep" key={`${node}-${index}`}>
              <span className="graphPathNode" data-kind={index % 2 === 0 ? "entity" : "edge"}>
                {node}
              </span>
              {index < path.length - 1 ? <span className="graphPathArrow" aria-hidden="true">→</span> : null}
            </span>
          ))}
        </div>
      ) : null}
      <div className="graphTableWrap">
        <table className="graphTable">
          <thead>
            <tr>
              <th>스테이션</th>
              <th>유형</th>
              <th>역량</th>
              <th>상태</th>
              <th className="graphTableNum">마지막 병목률</th>
            </tr>
          </thead>
          <tbody>
            {stations.map((station) => (
              <tr key={String(station.station_id)}>
                <td><strong>#{String(station.station_id)}</strong></td>
                <td>{station.station_type ?? "—"}</td>
                <td>
                  <span className="graphCaps">
                    {station.capabilities.length > 0
                      ? station.capabilities.map((cap) => (
                          <span className="graphCapChip" key={cap}>{cap}</span>
                        ))
                      : "—"}
                  </span>
                </td>
                <td>{station.state ?? "—"}</td>
                <td className="graphTableNum">
                  <span className="graphBottleneck" data-has={station.bottleneck_rate != null}>
                    {formatBottleneck(station.bottleneck_rate)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {latest_bottleneck ? (
        <div className="graphFootnote">
          최신 셀 병목률 {latest_bottleneck.value}% · 실행 {latest_bottleneck.run_id.slice(-8)}
        </div>
      ) : null}
      <time>{formatTime(at)}</time>
    </article>
  );
}

function sessionTitle(session: SessionSummary): string {
  // Surface the distinguishing user request first so older sessions are identifiable
  // (the long shared prefix made every row look the same).
  const userQuestion = session.first_user_message_preview?.trim() || session.last_message_preview?.trim();
  return userQuestion || sessionTitlePrefix;
}

function updateDashboardFromTelemetry(dashboard: OverlayDashboard, telemetry: ProcessTelemetry): OverlayDashboard {
  const metricValues: Record<string, number> = {
    throughput: telemetry.throughput,
    uptime: telemetry.uptime * 100,
    "avg-wait-time": telemetry.avg_wait_time,
    "collision-risk": telemetry.collision_risk,
    "active-agvs": telemetry.active_agvs
  };

  return {
    ...dashboard,
    cell_id: telemetry.cell_id || dashboard.cell_id,
    generated_at: telemetry.measured_at || new Date().toISOString(),
    metrics: dashboard.metrics.map((metric) => {
      const nextValue = metricValues[metric.id];
      if (typeof nextValue !== "number") return metric;
      const series = [...metric.series.slice(-7), nextValue];
      return {...metric, value: nextValue, series};
    })
  };
}

function updateDashboardFromProcess(dashboard: OverlayDashboard, process: ProcessSnapshot): OverlayDashboard {
  const metricValues: Record<string, number> = {
    throughput: process.throughput,
    // Guard uptime: an absent value (e.g. the idle reset frame sent when UE stops
    // emitting) must leave the card untouched, not force it to 0%.
    uptime: typeof process.uptime === "number" ? process.uptime * 100 : NaN,
    "avg-wait-time": process.avg_wait_time,
    "collision-risk": process.collision_risk,
    "active-agvs": process.active_agvs
  };

  return {
    ...dashboard,
    generated_at: new Date().toISOString(),
    metrics: dashboard.metrics.map((metric) => {
      const nextValue = metricValues[metric.id];
      if (typeof nextValue !== "number" || Number.isNaN(nextValue)) return metric;
      const series = [...metric.series.slice(-7), nextValue];
      return {...metric, value: nextValue, series};
    })
  };
}

const stateLabels: Record<string, string> = {
  IDLE: "대기",
  MOVING_TO_PICKUP: "픽업 이동",
  LOADING: "적재 중",
  MOVING_TO_DROPOFF: "하역 이동",
  UNLOADING: "하역 중",
  WAITING_AT_SECTION: "교차로 대기",
  STOPPED_COLLISION: "충돌 정지",
  STOPPED_OPERATION: "가동 정지"
};

function stateLabel(state: string): string {
  return stateLabels[state] ?? state;
}

function batteryLevel(battery: number): string {
  if (battery <= 25) return "low";
  if (battery <= 50) return "mid";
  return "high";
}

function BatteryBar({battery}: {battery: number}) {
  const pct = Math.max(0, Math.min(100, battery));
  return (
    <div className="batteryBar" data-level={batteryLevel(pct)}>
      <span style={{width: `${pct}%`}} />
      <em>{pct.toFixed(0)}%</em>
    </div>
  );
}

function clampProgress(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
}

function displayProgressPercent(hud: HudSnapshot): number {
  const rawProgress = clampProgress(hud.progress_percent);
  const speed = Math.max(0.1, hud.speed_multiplier || 1);
  if (hud.progress_basis === "simulated_time") {
    return rawProgress;
  }
  if (
    typeof hud.sim_elapsed_seconds === "number" &&
    typeof hud.sim_target_duration_seconds === "number" &&
    hud.sim_target_duration_seconds > 0
  ) {
    return clampProgress((hud.sim_elapsed_seconds / hud.sim_target_duration_seconds) * 100);
  }
  return clampProgress(rawProgress * speed);
}


function AgvHud({agv}: {agv: AgvTelemetry | null}) {
  if (!agv) {
    return (
      <div className="agvHud" data-empty="true">
        <strong>OVERVIEW</strong>
        <span>전체 셀 뷰 · AGV를 선택하면 HUD가 표시됩니다.</span>
      </div>
    );
  }

  return (
    <div className="agvHud">
      <div className="agvHudHead">
        <strong>{agv.agv_id}</strong>
        <span className="agvHudState" data-state={agv.state}>
          {stateLabel(agv.state)}
        </span>
      </div>
      <dl className="agvHudGrid">
        <div>
          <dt>배터리</dt>
          <dd>
            <BatteryBar battery={agv.battery} />
          </dd>
        </div>
        <div>
          <dt>목적지</dt>
          <dd>{agv.destination || "-"}</dd>
        </div>
        <div>
          <dt>속도</dt>
          <dd>
            {agv.speed.toFixed(1)} <span>u/s</span>
          </dd>
        </div>
        <div>
          <dt>적재</dt>
          <dd>{agv.carrying_load ? "적재중" : "비어있음"}</dd>
        </div>
      </dl>
    </div>
  );
}

function AgvMonitorGrid({
  agvs,
  selectedAgvId,
  onSelect,
  onClose
}: {
  agvs: AgvTelemetry[];
  selectedAgvId: string;
  onSelect: (agvId: string) => void;
  onClose: () => void;
}) {
  return (
    <aside className="agvMonitorPanel" aria-label="AGV list">
      <div className="agvMonitorHeader">
        <strong>AGV 목록 · AGV List</strong>
        <button type="button" aria-label="Close AGV list" onClick={onClose}>
          x
        </button>
      </div>
      <div className="agvMonitorGrid">
        {agvs.length > 0 ? (
          agvs.map((agv) => (
            <button
              type="button"
              key={agv.agv_id}
              className="agvMonitorCard"
              data-active={agv.agv_id === selectedAgvId}
              onClick={() => onSelect(agv.agv_id)}
            >
              <div className="agvMonitorTop">
                <strong>{agv.agv_id}</strong>
                <span data-state={agv.state}>{stateLabel(agv.state)}</span>
              </div>
              <BatteryBar battery={agv.battery} />
              <dl>
                <div>
                  <dt>목적지</dt>
                  <dd>{agv.destination || "-"}</dd>
                </div>
                <div>
                  <dt>속도</dt>
                  <dd>{agv.speed.toFixed(1)} u/s</dd>
                </div>
                <div>
                  <dt>완료</dt>
                  <dd>{agv.completed_tasks ?? 0}건</dd>
                </div>
              </dl>
            </button>
          ))
        ) : (
          <p className="agvMonitorEmpty">실시간 AGV 텔레메트리를 기다리는 중입니다.</p>
        )}
      </div>
    </aside>
  );
}

function VcoreHud({hud, runId}: {hud: HudSnapshot | null; runId?: string | null}) {
  if (!hud) {
    return null;
  }
  const status = hud.running ? (hud.paused ? "PAUSED" : "RUNNING") : "IDLE";
  const live = hud.running && !hud.paused;
  const progress = displayProgressPercent(hud);
  const progressMode = hud.progress_basis === "simulated_time" ? "sim" : "speed-adjusted";
  return (
    <div className="vcoreHud" aria-label="Simulation HUD">
      <div className="vcoreHudHead">
        <strong>VCORE VIRTUAL PROCESS</strong>
        <span className="vcoreHudStatus" data-live={live}>
          {status}
        </span>
        {runId ? <span className="vcoreHudRunId">RUN #{runId}</span> : null}
      </div>
      <p className="vcoreHudMeta">
        Speed {hud.speed_multiplier.toFixed(0)}x · Progress {progress.toFixed(0)}% ({progressMode}) · Policy{" "}
        {hud.policy_id || "-"}
      </p>
      <div className="vcoreHudBar" aria-hidden="true">
        <span style={{width: `${progress}%`}} />
      </div>
      <p className="vcoreHudCounters" data-alert={hud.collisions > 0}>
        Tasks {hud.tasks_completed} · Collisions {hud.collisions}
      </p>
      {hud.verdict_summary ? (
        <p className="vcoreHudVerdict" data-pass={hud.verdict_passed}>
          ACCEPTANCE {hud.verdict_summary}
        </p>
      ) : null}
      {hud.recent_events.length > 0 ? (
        <div className="vcoreHudEvents">
          <span className="vcoreHudEventsHead">RECENT EVENTS</span>
          {hud.recent_events.map((line, index) => (
            <span
              key={`${index}-${line}`}
              className="vcoreHudEvent"
              data-alert={line.includes("COLLISION") || line.includes("BOTTLENECK")}
            >
              {line}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const runStatusLabels: Record<string, string> = {
  created: "생성됨",
  starting: "시작 중",
  running: "실행 중",
  paused: "일시정지",
  stopped: "정지됨",
  completed: "완료",
  failed: "실패"
};

function runKpiValue(run: SimulationRun, key: string): number | null {
  const value = run.kpis_json?.[key];
  return typeof value === "number" ? value : null;
}

function SimRunTimes({run}: {run: SimulationRun}) {
  const endText = run.ended_at ? formatDateTimeKst(run.ended_at) : ["running", "paused", "starting"].includes(run.status) ? "In progress" : "-";
  return (
    <dl className="simRunTimes" aria-label="Simulation run times in KST">
      <div>
        <dt>Start (KST)</dt>
        <dd>{formatDateTimeKst(run.started_at)}</dd>
      </div>
      <div>
        <dt>End (KST)</dt>
        <dd>{endText}</dd>
      </div>
    </dl>
  );
}

function SimulationPanel({
  simulations,
  selectedSimulationId,
  draft,
  activeRun,
  latestRuns,
  busy,
  configOpen,
  onClose,
  onCloseConfig,
  onSelectSimulation,
  onDraftChange,
  onSave,
  onNew,
  onDuplicate,
  onDelete,
  onDeleteSimulation,
  onRun,
  onPause,
  onResume,
  onStop,
  onSpeed
}: {
  simulations: Simulation[];
  selectedSimulationId: string | null;
  draft: SimulationRequest;
  activeRun: SimulationRun | null;
  latestRuns: SimulationRun[];
  busy: boolean;
  configOpen: boolean;
  onClose: () => void;
  onCloseConfig: () => void;
  onSelectSimulation: (simulation: Simulation) => void;
  onDraftChange: (draft: SimulationRequest) => void;
  onSave: () => void;
  onNew: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onDeleteSimulation: (simulationId: string) => void;
  onRun: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onSpeed: (speed: number) => void;
}) {
  const canControl = Boolean(activeRun && ["running", "paused"].includes(activeRun.status));
  const [resultRunId, setResultRunId] = useState<string | null>(null);

  const resultRun = resultRunId ? (latestRuns.find((r) => r.run_id === resultRunId) ?? null) : null;
  const resultKpis = resultRun ? parseReportKpis(resultRun.kpis_json) : null;
  const resultVerdict = resultRun ? parseReportVerdict(resultRun.result_json?.verdict) : null;
  const resultTone = resultVerdict ? (resultVerdict.passed ? "pass" : "warn") : "info";

  const updateNumber = (key: keyof SimulationRequest, value: string) => {
    onDraftChange({...draft, [key]: Number(value)});
  };

  return (
    <>
      <aside className="simSideTab" aria-label="Simulation studio">
        <div className="simSideHeader">
          <div>
            <strong>Simulation Studio</strong>
            <span>{activeRun ? `${runStatusLabels[activeRun.status] ?? activeRun.status} · ${activeRun.run_id.slice(0, 8)}` : "준비 완료"}</span>
          </div>
          <button type="button" aria-label="Close simulation studio" onClick={onClose}>
            x
          </button>
        </div>

        <div className="simSideBody">
          <section className="simBlock simBlockGrow">
            <div className="simBlockHead">
              <span>시뮬레이션 목록</span>
              <button type="button" className="simAddButton" onClick={onNew} disabled={busy}>
                + 추가
              </button>
            </div>
            <div className="simSimulationList">
              {simulations.length > 0 ? (
                simulations.map((simulation) => (
                  <div
                    className="simSimulationRow"
                    key={simulation.simulation_id}
                    data-active={simulation.simulation_id === selectedSimulationId}
                  >
                    <button type="button" className="simSimulationOpen" onClick={() => onSelectSimulation(simulation)}>
                      <strong>{simulation.name}</strong>
                      <span>{simulation.agv_count} AGV · {simulation.speed_multiplier}x · {simulation.workload_percent}%</span>
                    </button>
                    <button
                      type="button"
                      className="simRowDelete"
                      aria-label={`${simulation.name} 삭제`}
                      disabled={busy}
                      onClick={() => onDeleteSimulation(simulation.simulation_id)}
                    >
                      🗑
                    </button>
                  </div>
                ))
              ) : (
                <p className="simEmpty">저장된 시뮬레이션이 없습니다. “+ 추가”로 만들어 보세요.</p>
              )}
            </div>
          </section>

          <section className="simBlock simBlockGrow">
            <div className="simBlockHead">
              <span>실행 기록 · {latestRuns.length}</span>
            </div>
            <div className="simRunList">
              {latestRuns.length > 0 ? (
                latestRuns.map((run) => {
                  const throughput = runKpiValue(run, "throughput");
                  const avgWaitTime = runKpiValue(run, "avg_wait_time");
                  const kpis = parseReportKpis(run.kpis_json);
                  const verdict = parseReportVerdict(run.result_json?.verdict);
                  const hasResult =
                    (run.status === "completed" || run.status === "failed") && (kpis !== null || verdict !== null);
                  return (
                    <article
                      className="simRunRow"
                      key={run.run_id}
                      data-active={run.run_id === activeRun?.run_id}
                      data-status={run.status}
                    >
                      <div className="simRunHead">
                        <div className="simRunTop">
                          <span className="simRunStatus" data-status={run.status}>
                            {runStatusLabels[run.status] ?? run.status}
                          </span>
                          <time>{run.run_id.slice(0, 8)}</time>
                        </div>
                        <SimRunTimes run={run} />
                        <dl className="simRunKpis">
                          <div>
                            <dt>Throughput</dt>
                            <dd>{throughput !== null ? throughput.toFixed(1) : "-"}</dd>
                          </div>
                          <div>
                            <dt>Wait</dt>
                            <dd>{avgWaitTime !== null ? `${avgWaitTime.toFixed(1)}s` : "-"}</dd>
                          </div>
                          <div>
                            <dt>Speed</dt>
                            <dd>{run.speed_multiplier}x</dd>
                          </div>
                        </dl>
                        {hasResult ? (
                          <button
                            type="button"
                            className="simRunViewResult"
                            data-active={resultRunId === run.run_id}
                            onClick={() => setResultRunId(resultRunId === run.run_id ? null : run.run_id)}
                          >
                            {resultRunId === run.run_id ? "결과 닫기 ▲" : "결과 보기 ▶"}
                          </button>
                        ) : null}
                      </div>
                    </article>
                  );
                })
              ) : (
                <p className="simEmpty">아직 실행 기록이 없습니다.</p>
              )}
            </div>
          </section>
        </div>
      </aside>

      {configOpen ? (
        <aside className="simConfigTab" aria-label="Simulation configuration">
          <div className="simSideHeader">
            <div>
              <strong>Configuration</strong>
              <span>{draft.name?.trim() || "새 시뮬레이션"}</span>
            </div>
            <button type="button" aria-label="Close configuration" onClick={onCloseConfig}>
              x
            </button>
          </div>

          <div className="simSideBody">
            <section className="simBlock">
              <div className="simBlockHead">
                <span>구성</span>
              </div>
              <div className="simulationForm">
                <label>
                  Name
                  <input value={draft.name} onChange={(event) => onDraftChange({...draft, name: event.target.value})} />
                </label>
                <label>
                  AGVs
                  <input type="number" min="1" max="20" value={draft.agv_count} onChange={(event) => updateNumber("agv_count", event.target.value)} />
                </label>
                <label>
                  Speed
                  <input type="number" min="0.1" max="20" step="0.1" value={draft.speed_multiplier} onChange={(event) => updateNumber("speed_multiplier", event.target.value)} />
                </label>
                <label>
                  Workload
                  <input type="number" min="1" max="300" value={draft.workload_percent} onChange={(event) => updateNumber("workload_percent", event.target.value)} />
                </label>
                <label>
                  Duration
                  <input type="number" min="10" max="86400" value={draft.duration_seconds} onChange={(event) => updateNumber("duration_seconds", event.target.value)} />
                </label>
                <label>
                  Bottleneck
                  <input type="number" min="0.1" max="3600" step="0.1" value={draft.bottleneck_threshold_sec} onChange={(event) => updateNumber("bottleneck_threshold_sec", event.target.value)} />
                </label>
              </div>
              <div className="simulationActions">
                <button type="button" onClick={onSave} disabled={busy || !draft.name.trim()}>Save</button>
                <button type="button" onClick={onDuplicate} disabled={busy || !selectedSimulationId}>Duplicate</button>
                <button type="button" onClick={onDelete} disabled={busy || !selectedSimulationId}>Delete</button>
              </div>
            </section>

            <section className="simBlock">
              <div className="simBlockHead">
                <span>재생 제어</span>
              </div>
              <div className="playbackActions">
                <button type="button" onClick={onRun} disabled={busy || !selectedSimulationId}>Run</button>
                <button type="button" onClick={onPause} disabled={busy || !canControl || activeRun?.status === "paused"}>Pause</button>
                <button type="button" onClick={onResume} disabled={busy || activeRun?.status !== "paused"}>Resume</button>
                <button type="button" onClick={onStop} disabled={busy || !canControl}>Stop</button>
              </div>
              <div className="speedStops" aria-label="Playback speed">
                {speedStops.map((speed) => (
                  <button
                    type="button"
                    key={speed}
                    data-active={activeRun?.speed_multiplier === speed}
                    disabled={busy || !canControl}
                    onClick={() => onSpeed(speed)}
                  >
                    {speed}x
                  </button>
                ))}
              </div>
            </section>
          </div>
        </aside>
      ) : null}

      {resultRun ? (
        <aside
          className="simResultTab"
          style={{left: configOpen ? "752px" : "398px"}}
          aria-label="Run result"
        >
          <div className="simSideHeader">
            <div>
              <strong>실행 결과</strong>
              <span>{runStatusLabels[resultRun.status] ?? resultRun.status} · {resultRun.run_id.slice(0, 8)}</span>
            </div>
            <button type="button" aria-label="Close result" onClick={() => setResultRunId(null)}>
              x
            </button>
          </div>
          <div className="simSideBody">
            <SimRunTimes run={resultRun} />
            {resultVerdict ? <ReportVerdictBanner verdict={resultVerdict} tone={resultTone} /> : null}
            {resultVerdict ? <ReportVerdictChips verdict={resultVerdict} /> : null}
            {resultKpis ? <ReportKpiGrid kpis={resultKpis} /> : null}
            {resultKpis ? <HeatmapGrid kpis={resultKpis} /> : null}
            {resultKpis ? <AiEvaluationCard kpis={resultKpis} verdict={resultVerdict} /> : null}
            {!resultKpis && !resultVerdict ? (
              <p className="simEmpty">결과 데이터가 아직 준비되지 않았습니다.</p>
            ) : null}
          </div>
        </aside>
      ) : null}
    </>
  );
}

export function App() {
  const storedState = useMemo(loadStoredState, []);
  const [sessionId, setSessionId] = useState<string | null>(storedState.sessionId);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [isSessionListOpen, setIsSessionListOpen] = useState(false);
  const [isSimPanelOpen, setIsSimPanelOpen] = useState(false);
  const [isConfigOpen, setIsConfigOpen] = useState(false);
  const [isCopilotOpen, setIsCopilotOpen] = useState(false);
  const [chatSimActive, setChatSimActive] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [collapsedMetrics, setCollapsedMetrics] = useState<Set<string>>(new Set());
  const [input, setInput] = useState("");
  const [items, setItems] = useState<TranscriptItem[]>([]);
  const [dashboard, setDashboard] = useState<OverlayDashboard>(fallbackDashboard);
  const [viewport, setViewport] = useState<UnrealViewport>(fallbackViewport);
  const [viewportState, setViewportState] = useState("connecting");
  const [activeZoneId, setActiveZoneId] = useState("zone-1");
  const [zoneBusyId, setZoneBusyId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [llmStatus, setLlmStatus] = useState<LlmStatus>({
    status: "loading",
    provider: "ollama",
    model: "",
    message: "Loading local LLM model.",
    updated_at: new Date().toISOString()
  });
  const [progressStatus, setProgressStatus] = useState<ProgressStatus | null>(null);
  const [logToasts, setLogToasts] = useState<LogToast[]>([]);
  const [connectionState, setConnectionState] = useState("initializing");
  const [error, setError] = useState<string | null>(null);
  const [agvs, setAgvs] = useState<AgvTelemetry[]>([]);
  const [processSnapshot, setProcessSnapshot] = useState<ProcessSnapshot | null>(null);
  const [hud, setHud] = useState<HudSnapshot | null>(null);
  const [selectedAgvId, setSelectedAgvId] = useState("overview");
  const [cameraBusy, setCameraBusy] = useState(false);
  const [isMonitorOpen, setIsMonitorOpen] = useState(false);
  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [selectedSimulationId, setSelectedSimulationId] = useState<string | null>(null);
  const [simulationDraft, setSimulationDraft] = useState<SimulationRequest>(defaultSimulationDraft);
  const [activeRun, setActiveRun] = useState<SimulationRun | null>(null);
  const [latestRuns, setLatestRuns] = useState<SimulationRun[]>([]);
  const [simulationBusy, setSimulationBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const requestInFlightRef = useRef(false);
  const logTimersRef = useRef<Map<string, number>>(new Map());
  // Mirrors selectedSimulationId so the long-lived chat WS closure reads the live selection.
  const selectedSimulationIdRef = useRef<string | null>(null);
  useEffect(() => {
    selectedSimulationIdRef.current = selectedSimulationId;
  }, [selectedSimulationId]);

  // Push an ephemeral work-log toast that auto-dismisses after 5 seconds.
  const pushLog = (id: string, text: string, at: string) => {
    if (logTimersRef.current.has(id)) return;
    setLogToasts((current) => {
      if (current.some((toast) => toast.id === id)) return current;
      return [...current, {id, text, at}].slice(-5);
    });
    const timer = window.setTimeout(() => {
      setLogToasts((current) => current.filter((toast) => toast.id !== id));
      logTimersRef.current.delete(id);
    }, 5000);
    logTimersRef.current.set(id, timer);
  };

  const logEvent = (event: DomainEvent) => {
    if (simActiveEvents.has(event.event_type)) setChatSimActive(true);
    if (event.event_type === "simulation.created") {
      const rid = payloadValue(event, "run_id");
      if (typeof rid === "string") setCurrentRunId(rid.slice(-8));
    }
    if (
      event.event_type === "simulation.run.updated" &&
      ["stopped", "completed", "failed"].includes(String(payloadValue(event, "status")))
    ) {
      setChatSimActive(false);
      setCurrentRunId(null);
    }
    if (!loggableEvents.has(event.event_type)) return;
    pushLog(event.event_id, eventText(event), event.occurred_at);
  };

  useEffect(() => {
    const timers = logTimersRef.current;
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      timers.clear();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const poll = () => {
      fetchLlmStatus()
        .then((status) => {
          if (cancelled) return;
          setLlmStatus(status);
          if (status.status !== "ready") {
            timer = window.setTimeout(poll, 1500);
          }
        })
        .catch(() => {
          if (cancelled) return;
          setLlmStatus((current) => ({
            ...current,
            status: "loading",
            message: "Connecting to the chatbot backend and loading the local LLM model.",
            updated_at: new Date().toISOString()
          }));
          timer = window.setTimeout(poll, 1500);
        });
    };

    poll();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, []);

  const selectedAgv = useMemo(
    () => agvs.find((agv) => agv.agv_id === selectedAgvId) ?? null,
    [agvs, selectedAgvId]
  );
  // The viewport must render the moment a sim starts — from the simulation panel,
  // from Firebase process telemetry, or from a chat-driven run (no activeRun).
  const isSimActive =
    (activeRun !== null && ["starting", "running", "paused"].includes(activeRun.status)) ||
    processSnapshot?.running === true ||
    chatSimActive;
  const viewportFrameUrl = useMemo(
    () => withPixelStreamingParams(viewport.stream_url),
    [viewport.stream_url]
  );

  const toggleMetric = (metricId: string) => {
    setCollapsedMetrics((current) => {
      const next = new Set(current);
      if (next.has(metricId)) {
        next.delete(metricId);
      } else {
        next.add(metricId);
      }
      return next;
    });
  };

  const chatItems = useMemo(
    () =>
      items
        .filter((item) => item.kind === "message" || item.kind === "event" || item.kind === "plan" || item.kind === "report" || item.kind === "graph")
        .slice(-12),
    [items]
  );
  const isLlmReady = llmStatus.status === "ready";
  const chatInputDisabled = !sessionId || isSending || !isLlmReady;

  useEffect(() => {
    let cancelled = false;
    // This same-origin endpoint is stable. Open it independently from viewport discovery:
    // EventSource reconnects after backend restarts, while a failed one-shot viewport fetch
    // previously left telemetry disabled until the user reloaded the whole page.
    const telemetry = openUnrealTelemetryStream(fallbackViewport.telemetry_sse_url);

    telemetry.onopen = () => setViewportState("connected");
    telemetry.addEventListener("telemetry", (event) => {
      try {
        const parsed = JSON.parse((event as MessageEvent).data) as ProcessTelemetry;
        setDashboard((current) => updateDashboardFromTelemetry(current, parsed));
      } catch {
        setViewportState("telemetry-error");
      }
    });
    telemetry.addEventListener("agvs", (event) => {
      try {
        setAgvs(JSON.parse((event as MessageEvent).data) as AgvTelemetry[]);
      } catch {
        /* ignore malformed frame */
      }
    });
    telemetry.addEventListener("process", (event) => {
      try {
        setProcessSnapshot(JSON.parse((event as MessageEvent).data) as ProcessSnapshot);
      } catch {
        /* ignore malformed frame */
      }
    });
    telemetry.addEventListener("hud", (event) => {
      try {
        setHud(JSON.parse((event as MessageEvent).data) as HudSnapshot);
      } catch {
        /* ignore malformed frame */
      }
    });
    telemetry.onerror = () => setViewportState("telemetry-reconnecting");

    fetchUnrealViewport()
      .then((payload) => {
        if (cancelled) return;
        setViewport(payload);
      })
      .catch(() => {
        if (!cancelled) {
          setViewport(fallbackViewport);
        }
      });

    return () => {
      cancelled = true;
      telemetry.close();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchOverlayDashboard()
      .then((payload) => {
        if (!cancelled) setDashboard(payload);
      })
      .catch(() => {
        if (!cancelled) setDashboard(fallbackDashboard);
      });

    const interval = window.setInterval(() => {
      fetchOverlayDashboard()
        .then((payload) => setDashboard(payload))
        .catch(() => undefined);
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  // Show the AGV list automatically while a simulation is live; hide it otherwise.
  useEffect(() => {
    setIsMonitorOpen(isSimActive);
  }, [isSimActive]);

  // Process SSE telemetry drives the metric cards and run state.
  useEffect(() => {
    if (!processSnapshot) return;
    // Telemetry is the authority once present: clear the chat-driven flag on stop.
    if (processSnapshot.running === false) setChatSimActive(false);
    setDashboard((current) => updateDashboardFromProcess(current, processSnapshot));
  }, [processSnapshot]);

  async function handleCameraSelect(agvId: string) {
    if (cameraBusy) return;
    setSelectedAgvId(agvId);
    setCameraBusy(true);
    try {
      await selectAgvCamera(agvId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Camera switch failed.");
    } finally {
      setCameraBusy(false);
    }
  }

  async function refreshSessions() {
    try {
      const response = await listSessions();
      const startedSessions = response.sessions.filter((session) => session.message_count > 0);
      setSessions(startedSessions);
      return startedSessions;
    } catch {
      setSessions([]);
      return [];
    }
  }

  async function refreshSimulationRuns(simulationId: string) {
    try {
      const response = await listSimulationRuns(simulationId);
      setLatestRuns(response.runs);
      const latestActive = response.runs.find((run) => ["running", "paused", "starting"].includes(run.status));
      if (latestActive) {
        setActiveRun(latestActive);
      } else if (activeRun && response.runs.some((run) => run.run_id === activeRun.run_id)) {
        setActiveRun(response.runs.find((run) => run.run_id === activeRun.run_id) ?? null);
      }
      return response.runs;
    } catch {
      setLatestRuns([]);
      return [];
    }
  }

  // Non-destructive list refresh for chat-driven simulation events: updates the list and the
  // selected simulation's run history without overwriting the operator's in-progress config draft.
  async function reloadSimulationList(preferredSimulationId?: string) {
    try {
      const response = await listSimulations();
      setSimulations(response.simulations);
      const current = preferredSimulationId || selectedSimulationIdRef.current;
      const target =
        (current
          ? response.simulations.find((simulation) => simulation.simulation_id === current)
          : null) ?? response.simulations[0];
      if (target) {
        if (target.simulation_id !== selectedSimulationIdRef.current) {
          setSelectedSimulationId(target.simulation_id);
          selectedSimulationIdRef.current = target.simulation_id;
          setSimulationDraft({
            name: target.name,
            agv_count: target.agv_count,
            speed_multiplier: target.speed_multiplier,
            workload_percent: target.workload_percent,
            policy_id: target.policy_id,
            duration_seconds: target.duration_seconds,
            bottleneck_threshold_sec: target.bottleneck_threshold_sec
          });
        }
        await refreshSimulationRuns(target.simulation_id);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to load simulations.");
    }
  }

  function refreshSimulationFromEvent(event: DomainEvent) {
    if (event.event_type !== "simulation.created" && event.event_type !== "simulation.run.updated") {
      return;
    }
    const simulationId = payloadValue(event, "simulation_id");
    void reloadSimulationList(typeof simulationId === "string" ? simulationId : undefined);
  }

  async function refreshSimulations() {
    try {
      const response = await listSimulations();
      setSimulations(response.simulations);
      const next = response.simulations.find((simulation) => simulation.simulation_id === selectedSimulationId) ?? response.simulations[0];
      if (next) {
        setSelectedSimulationId(next.simulation_id);
        setSimulationDraft({
          name: next.name,
          agv_count: next.agv_count,
          speed_multiplier: next.speed_multiplier,
          workload_percent: next.workload_percent,
          policy_id: next.policy_id,
          duration_seconds: next.duration_seconds,
          bottleneck_threshold_sec: next.bottleneck_threshold_sec
        });
        await refreshSimulationRuns(next.simulation_id);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to load simulations.");
    }
  }

  useEffect(() => {
    void refreshSimulations();
  }, []);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;

    const connectSession = async (targetSessionId: string) => {
      setSessionId(targetSessionId);
      setConnectionState("loading");
      try {
        const history = await fetchSessionMessages(targetSessionId);
        if (!cancelled) {
          setItems(history.messages.map(toAssistantItem));
        }
      } catch (reason) {
        if (!cancelled) {
          const message = reason instanceof Error ? reason.message : "Failed to load chat history.";
          if (message.includes("404")) {
            window.localStorage.removeItem(storageKey);
            setItems([]);
            setSessionId(null);
            return;
          }
          setError(message);
        }
      }
      socket = openSessionEvents(targetSessionId);
      socket.addEventListener("open", () => setConnectionState("connected"));
      socket.addEventListener("close", () => setConnectionState("closed"));
      socket.addEventListener("error", () => setConnectionState("error"));
      socket.addEventListener("message", (message) => {
        const event = JSON.parse(message.data) as DomainEvent;
        const item = toTranscriptItem(event);
        const progress = progressStatusFromEvent(event);
        logEvent(event);
        // A chat-driven simulation now mirrors into the simulation store; pull the list so
        // the side tab shows the chatbot-created simulation and live run status immediately.
        refreshSimulationFromEvent(event);
        if (progress && (requestInFlightRef.current || event.event_type === "chat.report.generating")) {
          setProgressStatus(progress);
        }
        // A simulation completes asynchronously (its duration timer fires long after the
        // chat turn that started it), so its final LLM report arrives only over this WS as
        // chat.report.generated — never on an HTTP response. Render it as an assistant
        // message, keyed by message_id so it dedupes against the synchronous HTTP delivery.
        if (event.event_type === "chat.report.generated") {
          const messageId = payloadValue(event, "message_id");
          const content = payloadValue(event, "content");
          const reportId = typeof messageId === "string" ? messageId : event.event_id;
          const text = typeof content === "string" ? content : eventText(event);
          const kpis = parseReportKpis(payloadValue(event, "kpis"));
          const verdict = parseReportVerdict(payloadValue(event, "verdict"));
          setProgressStatus(null);
          setItems((current) => {
            if (current.some((currentItem) => currentItem.id === reportId)) return current;
            return [...current, {id: reportId, kind: "report", text, at: event.occurred_at, kpis, verdict}];
          });
          return;
        }
        const graphEvidence = graphEvidenceFromEvent(event);
        if (graphEvidence) {
          const graphId = `${event.event_id}-graph`;
          setItems((current) =>
            current.some((currentItem) => currentItem.id === graphId)
              ? current
              : [...current, {id: graphId, kind: "graph", evidence: graphEvidence, at: event.occurred_at}]
          );
          return;
        }
        if (!shouldAppendEventToTranscript(event)) {
          return;
        }
        setItems((current) => {
          if (current.some((currentItem) => currentItem.id === item.id)) return current;
          return [...current, item];
        });
      });
    };

    if (sessionId) {
      void refreshSessions();
      void connectSession(sessionId);
      return () => {
        cancelled = true;
        socket?.close();
      };
    }

    refreshSessions()
      .then((availableSessions) => {
        if (cancelled) return;
        const latestSession = availableSessions[0];
        if (latestSession) {
          void connectSession(latestSession.session_id);
          return;
        }
        createSession()
          .then((session) => {
            if (!cancelled) {
              void refreshSessions();
              void connectSession(session.session_id);
            }
          })
          .catch((reason: unknown) => {
            setError(reason instanceof Error ? reason.message : "Failed to create chat session.");
            setConnectionState("error");
          });
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Failed to list chat sessions.");
        setConnectionState("error");
      });

    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [sessionId]);

  useEffect(() => {
    window.localStorage.setItem(storageKey, JSON.stringify({sessionId, items: []}));
  }, [sessionId]);

  useEffect(() => {
    listRef.current?.scrollTo({top: listRef.current.scrollHeight, behavior: "smooth"});
  }, [chatItems.length, isSending, progressStatus?.id]);

  async function submitMessage() {
    if (chatInputDisabled || !input.trim()) return;

    const text = input.trim();
    setInput("");
    setError(null);
    setIsSending(true);
    requestInFlightRef.current = true;
    setProgressStatus({
      id: `progress-${crypto.randomUUID()}`,
      title: "메시지 수신",
      text: "사용자 메시지를 수신하고 세션 스트림을 동기화했습니다.",
      at: new Date().toISOString()
    });
    setItems((current) => [
      ...current,
      {id: `local-${crypto.randomUUID()}`, kind: "message", role: "user", text, at: new Date().toISOString()}
    ]);

    try {
      const response = await sendMessage(sessionId, text);
      response.events.forEach(logEvent);
      response.events.forEach(refreshSimulationFromEvent);

      // Reveal each plan/event item in order, pausing between them, so the planning process
      // appears step-by-step. The assistant reply is appended only after the last step lands.
      const transcriptEvents = response.events.filter(shouldAppendEventToTranscript);
      for (const event of transcriptEvents) {
        const item = toTranscriptItem(event);
        setItems((current) =>
          current.some((currentItem) => currentItem.id === item.id) ? current : [...current, item]
        );
        const progress = progressStatusFromEvent(event);
        if (progress) setProgressStatus(progress);
        await new Promise((resolve) => setTimeout(resolve, PLAN_STEP_REVEAL_MS));
      }

      // GraphRAG evidence card: render the relationship/KPI table above the prose answer.
      for (const event of response.events) {
        const evidence = graphEvidenceFromEvent(event);
        if (!evidence) continue;
        const graphId = `${event.event_id}-graph`;
        setItems((current) =>
          current.some((currentItem) => currentItem.id === graphId)
            ? current
            : [...current, {id: graphId, kind: "graph", evidence, at: event.occurred_at}]
        );
      }

      setItems((current) =>
        current.some((currentItem) => currentItem.id === response.message.message_id)
          ? current
          : [...current, toAssistantItem(response.message)]
      );
      setProgressStatus(null);
      void refreshSessions();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Message send failed.");
      setProgressStatus(null);
    } finally {
      requestInFlightRef.current = false;
      setIsSending(false);
    }
  }

  async function openNewSession() {
    if (isSending) return;
    setError(null);
    setItems([]);
    setProgressStatus(null);
    try {
      const session = await createSession();
      setSessionId(session.session_id);
      await refreshSessions();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to open a new session.");
    }
  }

  function openExistingSession(targetSessionId: string) {
    if (targetSessionId === sessionId || isSending) return;
    setError(null);
    setItems([]);
    setProgressStatus(null);
    setIsSessionListOpen(false);
    setSessionId(targetSessionId);
  }

  async function deleteExistingSession(targetSessionId: string) {
    if (isSending) return;
    setError(null);
    try {
      await deleteSession(targetSessionId);
      const remaining = await refreshSessions();
      if (targetSessionId === sessionId) {
        // The active session was removed — switch to the next available one or open a fresh session.
        setItems([]);
        setProgressStatus(null);
        const next = remaining[0];
        if (next) {
          setSessionId(next.session_id);
        } else {
          const session = await createSession();
          setSessionId(session.session_id);
          await refreshSessions();
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to delete session.");
    }
  }

  function selectSimulation(simulation: Simulation) {
    setSelectedSimulationId(simulation.simulation_id);
    setSimulationDraft({
      name: simulation.name,
      agv_count: simulation.agv_count,
      speed_multiplier: simulation.speed_multiplier,
      workload_percent: simulation.workload_percent,
      policy_id: simulation.policy_id,
      duration_seconds: simulation.duration_seconds,
      bottleneck_threshold_sec: simulation.bottleneck_threshold_sec
    });
    void refreshSimulationRuns(simulation.simulation_id);
  }

  async function saveSimulation() {
    setSimulationBusy(true);
    setError(null);
    try {
      const saved = selectedSimulationId
        ? await updateSimulation(selectedSimulationId, simulationDraft)
        : await createSimulation(simulationDraft);
      setSelectedSimulationId(saved.simulation_id);
      await refreshSimulations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulation save failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function duplicateSelectedSimulation() {
    if (!selectedSimulationId) return;
    setSimulationBusy(true);
    setError(null);
    try {
      const duplicated = await duplicateSimulation(selectedSimulationId);
      setSelectedSimulationId(duplicated.simulation_id);
      await refreshSimulations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulation duplicate failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function deleteSimulationById(simulationId: string) {
    setSimulationBusy(true);
    setError(null);
    try {
      await deleteSimulation(simulationId);
      if (simulationId === selectedSimulationId) {
        setSelectedSimulationId(null);
        setActiveRun(null);
        setLatestRuns([]);
        setSimulationDraft(defaultSimulationDraft);
      }
      await refreshSimulations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulation delete failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function deleteSelectedSimulation() {
    if (!selectedSimulationId) return;
    await deleteSimulationById(selectedSimulationId);
  }

  async function startSelectedSimulation() {
    if (!selectedSimulationId) return;
    setSimulationBusy(true);
    setError(null);
    try {
      const run = await runSimulation(selectedSimulationId);
      setActiveRun(run);
      await refreshSimulationRuns(selectedSimulationId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulation run failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function pauseActiveRun() {
    if (!activeRun) return;
    setSimulationBusy(true);
    try {
      setActiveRun(await pauseRun(activeRun.run_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run pause failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function resumeActiveRun() {
    if (!activeRun) return;
    setSimulationBusy(true);
    try {
      setActiveRun(await resumeRun(activeRun.run_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run resume failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function stopActiveRun() {
    if (!activeRun) return;
    setSimulationBusy(true);
    try {
      const stopped = await stopRun(activeRun.run_id);
      setActiveRun(stopped);
      setChatSimActive(false);
      if (selectedSimulationId) await refreshSimulationRuns(selectedSimulationId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run stop failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function changeActiveRunSpeed(speed: number) {
    if (!activeRun) return;
    setSimulationBusy(true);
    try {
      setActiveRun(await setRunSpeed(activeRun.run_id, speed));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run speed failed.");
    } finally {
      setSimulationBusy(false);
    }
  }

  async function loadActiveRunResult() {
    if (!activeRun) return;
    try {
      const result = await fetchRunResult(activeRun.run_id);
      setActiveRun(result.run);
    } catch {
      // Result polling is opportunistic; live Firebase telemetry still drives the dashboard.
    }
  }

  useEffect(() => {
    if (!activeRun || !["running", "paused"].includes(activeRun.status)) return;
    const interval = window.setInterval(() => {
      void loadActiveRunResult();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [activeRun?.run_id, activeRun?.status]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitMessage();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitMessage();
    }
  }

  async function handleZoneClick(zoneId: string) {
    if (zoneBusyId) return;
    setError(null);
    setZoneBusyId(zoneId);

    try {
      // Each ZONE button maps to one of the three Process-level cameras. The backend
      // proxies the zone id to UE5 /camera/select, which blends to the tagged camera.
      await selectAgvCamera(zoneId);
      setActiveZoneId(zoneId);
      // Switching to a zone camera releases any per-AGV chase camera + HUD.
      setSelectedAgvId("overview");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unreal zone request failed.");
    } finally {
      setZoneBusyId(null);
    }
  }

  return (
    <main className="overlayShell">
      <section className="unrealViewport" aria-label="Unreal Engine viewport">
        {isSimActive ? (
          <>
            <iframe
              title="UE5 camera view"
              src={viewportFrameUrl}
              allow="autoplay; fullscreen; microphone; camera; clipboard-read; clipboard-write"
              onLoad={() => setViewportState("connected")}
            />
            <VcoreHud hud={hud} runId={currentRunId} />
            <button
              type="button"
              className="monitorToggle"
              aria-pressed={isMonitorOpen}
              onClick={() => setIsMonitorOpen((current) => !current)}
            >
              AGV 목록 · AGV List
            </button>
            {selectedAgv ? <AgvHud agv={selectedAgv} /> : null}
            {isMonitorOpen ? (
              <AgvMonitorGrid
                agvs={agvs}
                selectedAgvId={selectedAgvId}
                onSelect={(agvId) => {
                  // Clicking an AGV switches the viewport to its camera; keep the
                  // list open so the operator can hop between AGV cameras.
                  void handleCameraSelect(agvId);
                }}
                onClose={() => setIsMonitorOpen(false)}
              />
            ) : null}
          </>
        ) : (
          <div className="viewportBlankScreen" />
        )}
      </section>
      <header className="topBar">
        <button
          type="button"
          className="hamburger"
          aria-label="Toggle simulation studio"
          aria-pressed={isSimPanelOpen}
          onClick={() => setIsSimPanelOpen((current) => !current)}
        >
          <span /><span /><span />
        </button>
        <strong>VIRTUAL PROCESS AI COMMAND HUB</strong>
        <span>{dashboard.cell_id}</span>
        <div className="topIcons" aria-hidden="true">
          <span>↻</span>
          <span>⌂</span>
        </div>
      </header>

      {isSimActive && (
        <nav className="zoneNav" aria-label="Zone navigation">
          {dashboard.zones.map((zone) => (
            <button
              type="button"
              key={zone.id}
              data-active={zone.id === activeZoneId}
              disabled={zoneBusyId !== null}
              onClick={() => void handleZoneClick(zone.id)}
            >
              <strong>{zone.name}</strong>
              <span>{zoneBusyId === zone.id ? "Requesting Unreal" : zone.subtitle}</span>
            </button>
          ))}
        </nav>
      )}

      <section className="commandFeed" aria-label="Work logs">
        {logToasts.map((toast) => (
          <p key={toast.id} className="logToast">
            <span aria-hidden="true">⌘</span>
            {toast.text}
          </p>
        ))}
      </section>

      <aside className="leftStack" aria-label="Farm metric panels">
        <div className="systemCard">
          <div>
            <strong>공정 인텔리전스</strong>
            <span>v2.04 · ULTRA HD</span>
          </div>
          <span aria-hidden="true">≡</span>
        </div>
        {dashboard.metrics
          .filter((metric) => metric.id !== "collision-risk" && (isSimActive || metric.id !== "throughput"))
          .map((metric) => (
            <MetricCard
              key={metric.id}
              metric={metric}
              collapsed={collapsedMetrics.has(metric.id)}
              onToggle={() => toggleMetric(metric.id)}
            />
          ))}
      </aside>

      {isSimPanelOpen ? (
        <SimulationPanel
          simulations={simulations}
          selectedSimulationId={selectedSimulationId}
          draft={simulationDraft}
          activeRun={activeRun}
          latestRuns={latestRuns}
          busy={simulationBusy}
          configOpen={isConfigOpen}
          onClose={() => setIsSimPanelOpen(false)}
          onCloseConfig={() => setIsConfigOpen(false)}
          onSelectSimulation={(simulation) => {
            selectSimulation(simulation);
            setIsConfigOpen(true);
          }}
          onDraftChange={setSimulationDraft}
          onSave={() => void saveSimulation()}
          onNew={() => {
            setSelectedSimulationId(null);
            setSimulationDraft({...defaultSimulationDraft, name: `Simulation ${simulations.length + 1}`});
            setIsConfigOpen(true);
          }}
          onDuplicate={() => void duplicateSelectedSimulation()}
          onDelete={() => void deleteSelectedSimulation()}
          onDeleteSimulation={(simulationId) => void deleteSimulationById(simulationId)}
          onRun={() => void startSelectedSimulation()}
          onPause={() => void pauseActiveRun()}
          onResume={() => void resumeActiveRun()}
          onStop={() => void stopActiveRun()}
          onSpeed={(speed) => void changeActiveRunSpeed(speed)}
        />
      ) : null}

      {isSessionListOpen ? (
        <aside className="sessionSideTab" aria-label="Chat session list">
          <div className="sessionSideHeader">
            <strong>Session List</strong>
            <button type="button" aria-label="Close session list" onClick={() => setIsSessionListOpen(false)}>
              x
            </button>
          </div>
          <div className="sessionList">
            {sessions.length > 0 ? (
              sessions.map((session) => (
                <div
                  className="sessionRow"
                  key={session.session_id}
                  data-active={session.session_id === sessionId}
                >
                  <button
                    type="button"
                    className="sessionOpen"
                    disabled={isSending}
                    onClick={() => openExistingSession(session.session_id)}
                  >
                    <strong>{sessionTitle(session)}</strong>
                    <span>
                      {session.message_count} messages · {formatTime(session.last_message_at || session.created_at || "")}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="sessionDelete"
                    aria-label="Delete session"
                    disabled={isSending}
                    onClick={() => void deleteExistingSession(session.session_id)}
                  >
                    🗑
                  </button>
                </div>
              ))
            ) : (
              <p>No completed sessions yet.</p>
            )}
          </div>
        </aside>
      ) : null}

      <aside className="copilotPanel" data-collapsed={!isCopilotOpen} aria-label="AI copilot chat">
        <header>
          <h2>AI 코파일럿</h2>
          <span data-state={connectionState}>{connectionState === "connected" ? "ONLINE" : "SYNC"}</span>
          <button
            type="button"
            className="copilotToggle"
            aria-label={isCopilotOpen ? "접기" : "펼치기"}
            onClick={() => setIsCopilotOpen((o) => !o)}
          >
            {isCopilotOpen ? "▼" : "▲"}
          </button>
        </header>

        {isCopilotOpen ? (
          <>
            <div className="sessionDock" aria-label="Chat sessions">
              <button
                type="button"
                className="sessionListToggle"
                aria-expanded={isSessionListOpen}
                onClick={() => setIsSessionListOpen((current) => !current)}
              >
                Session List
              </button>
            </div>

            <div className="chatLog" ref={listRef}>
              {chatItems.map((item) => {
                if (item.kind === "message") {
                  return (
                    <article className={`copilotBubble ${item.role}`} key={item.id}>
                      <MessageContent text={item.text} />
                      <time>{formatTime(item.at)}</time>
                    </article>
                  );
                }

                if (item.kind === "report") {
                  return <ReportCard key={item.id} text={item.text} at={item.at} kpis={item.kpis} verdict={item.verdict} />;
                }

                if (item.kind === "graph") {
                  return <GraphRagCard key={item.id} evidence={item.evidence} at={item.at} />;
                }

                if (item.kind === "plan") {
                  return (
                    <article className="copilotBubble plan" key={item.id}>
                      <strong>
                        Planning {item.index}/{item.total}
                      </strong>
                      <MessageContent text={item.text} />
                      <time>{formatTime(item.at)}</time>
                    </article>
                  );
                }

                return (
                  <article className="copilotBubble event" key={item.id}>
                    <strong>{eventLabels[item.eventType] ?? item.eventType}</strong>
                    <MessageContent text={item.text} />
                  </article>
                );
              })}
              {progressStatus ? (
                <article className="copilotBubble progress" key={progressStatus.id}>
                  <span className="progressSpinner" aria-hidden="true" />
                  <div>
                    <strong>{progressStatus.title}</strong>
                    <MessageContent text={progressStatus.text} />
                    <time>{formatTime(progressStatus.at)}</time>
                  </div>
                </article>
              ) : null}
            </div>

            {error ? <div className="errorBanner">{error}</div> : null}
            {!isLlmReady ? (
              <div className="modelLoadingBanner" role="status" aria-live="polite">
                <span className="progressSpinner" aria-hidden="true" />
                <div>
                  <strong>{llmStatus.status === "failed" ? "LLM model unavailable" : "LLM model loading"}</strong>
                  <p>{llmStatus.message || "Preparing the local model before chat starts."}</p>
                </div>
              </div>
            ) : null}

            <div className="newSessionBar">
              <button type="button" onClick={() => void openNewSession()} disabled={isSending}>
                Open New Session
              </button>
            </div>

            <form className="copilotComposer" onSubmit={handleSubmit}>
              <textarea
                aria-label="AI command"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                disabled={chatInputDisabled}
                placeholder={isLlmReady ? "Ask for the content form you require." : "The local LLM model is still loading."}
                rows={2}
              />
              <button type="submit" disabled={chatInputDisabled || !input.trim()}>
                {isSending ? "..." : "run"}
              </button>
            </form>
          </>
        ) : null}
      </aside>

      <div className="apiBadge">API {config.apiBaseUrl.replace(/^https?:\/\//, "")}</div>
    </main>
  );
}
