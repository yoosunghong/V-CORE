import type {
  CameraSelectResponse,
  ChatResponse,
  OverlayDashboard,
  ProcessTelemetry,
  RunListResponse,
  RunResultResponse,
  SimulationListResponse,
  SimulationRequest,
  SimulationRun,
  SessionListResponse,
  SessionMessagesResponse,
  SessionResponse,
  Simulation,
  UnrealViewport,
  UnrealZoneFocusResponse
} from "./types";

const trimRight = (value: string) => value.replace(/\/+$/, "");

const _hostname = window.location.hostname || "localhost";
const _isLocal = _hostname === "localhost" || _hostname === "127.0.0.1";
// When served through a reverse proxy (e.g. ngrok), use same-origin so nginx routes
// /api/ and /llm/ to the backend. For local dev, point directly at :8000.
const defaultApiBaseUrl = _isLocal
  ? `${window.location.protocol}//${_hostname}:8000`
  : `${window.location.protocol}//${window.location.host}`;
const defaultWsBaseUrl = _isLocal
  ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${_hostname}:8000`
  : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

function resolveBaseUrl(value: string | undefined, fallback: string): string {
  const resolved = value?.trim() || fallback;
  return trimRight(resolved);
}

const apiBaseUrl = resolveBaseUrl(import.meta.env.VITE_API_BASE_URL, defaultApiBaseUrl);

const wsBaseUrl = resolveBaseUrl(import.meta.env.VITE_WS_BASE_URL, defaultWsBaseUrl);

export const config = {
  apiBaseUrl,
  wsBaseUrl
};

const unrealClientId = "ue-webview";

export type LlmStatus = {
  status: "loading" | "ready" | "failed" | string;
  provider: string;
  model: string;
  message: string;
  updated_at: string;
};

export async function fetchLlmStatus(): Promise<LlmStatus> {
  const response = await fetch(`${apiBaseUrl}/llm/status`);

  if (!response.ok) {
    throw new Error(`LLM status fetch failed: ${response.status}`);
  }

  return response.json();
}

export async function createSession(): Promise<SessionResponse> {
  const response = await fetch(`${apiBaseUrl}/chat/sessions`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({user_id: "webview-demo-user", unreal_client_id: unrealClientId})
  });

  if (!response.ok) {
    throw new Error(`Session create failed: ${response.status}`);
  }

  return response.json();
}

export async function listSessions(): Promise<SessionListResponse> {
  const params = new URLSearchParams({
    user_id: "webview-demo-user",
    unreal_client_id: unrealClientId,
    limit: "20"
  });
  const response = await fetch(`${apiBaseUrl}/chat/sessions?${params.toString()}`);

  if (!response.ok) {
    throw new Error(`Session list failed: ${response.status}`);
  }

  return response.json();
}

export async function fetchSessionMessages(sessionId: string): Promise<SessionMessagesResponse> {
  const params = new URLSearchParams({
    limit: "40",
    max_content_chars: "1200"
  });
  const response = await fetch(
    `${apiBaseUrl}/chat/sessions/${encodeURIComponent(sessionId)}/messages?${params.toString()}`
  );

  if (!response.ok) {
    throw new Error(`Session history fetch failed: ${response.status}`);
  }

  return response.json();
}

export async function sendMessage(sessionId: string, message: string): Promise<ChatResponse> {
  const correlationId = `corr_web_${crypto.randomUUID().replaceAll("-", "")}`;
  const response = await fetch(`${apiBaseUrl}/chat/messages`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-correlation-id": correlationId
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      user_id: "webview-demo-user",
      unreal_client_id: unrealClientId,
      idempotency_key: `chat-web-${correlationId}`
    })
  });

  if (!response.ok) {
    throw new Error(`Message send failed: ${response.status}`);
  }

  return response.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE"
  });

  if (!response.ok && response.status !== 404) {
    throw new Error(`Session delete failed: ${response.status}`);
  }
}

export function openSessionEvents(sessionId: string): WebSocket {
  return new WebSocket(`${wsBaseUrl}/chat/sessions/${sessionId}/events`);
}

export async function fetchOverlayDashboard(): Promise<OverlayDashboard> {
  const response = await fetch(`${apiBaseUrl}/dashboard/overlay`);

  if (!response.ok) {
    throw new Error(`Overlay dashboard fetch failed: ${response.status}`);
  }

  return response.json();
}

export async function fetchUnrealViewport(): Promise<UnrealViewport> {
  const response = await fetch(`${apiBaseUrl}/unreal/viewport`);

  if (!response.ok) {
    throw new Error(`Unreal viewport config fetch failed: ${response.status}`);
  }

  return response.json();
}

export function openUnrealTelemetryStream(pathOrUrl: string): EventSource {
  const url = pathOrUrl.startsWith("http") ? pathOrUrl : `${apiBaseUrl}${pathOrUrl}`;
  return new EventSource(url);
}

export type {ProcessTelemetry};

export async function selectAgvCamera(agvId: string): Promise<CameraSelectResponse> {
  const response = await fetch(`${apiBaseUrl}/unreal/cameras/${encodeURIComponent(agvId)}/select`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      unreal_client_id: unrealClientId,
      idempotency_key: `chat-web-camera-${agvId}`
    })
  });

  if (!response.ok) {
    throw new Error(`Camera select failed: ${response.status}`);
  }

  return response.json();
}

export async function focusUnrealZone(zoneId: string): Promise<UnrealZoneFocusResponse> {
  const response = await fetch(`${apiBaseUrl}/unreal/zones/${encodeURIComponent(zoneId)}/focus`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({
      unreal_client_id: unrealClientId,
      idempotency_key: `chat-web-zone-${zoneId}`
    })
  });

  if (!response.ok) {
    throw new Error(`Unreal zone focus failed: ${response.status}`);
  }

  return response.json();
}

export async function listSimulations(): Promise<SimulationListResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/simulations`);
  if (!response.ok) {
    throw new Error(`Simulation list failed: ${response.status}`);
  }
  return response.json();
}

export async function createSimulation(payload: SimulationRequest): Promise<Simulation> {
  const response = await fetch(`${apiBaseUrl}/api/v1/simulations`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Simulation create failed: ${response.status}`);
  }
  return response.json();
}

export async function updateSimulation(simulationId: string, payload: SimulationRequest): Promise<Simulation> {
  const response = await fetch(`${apiBaseUrl}/api/v1/simulations/${encodeURIComponent(simulationId)}`, {
    method: "PUT",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Simulation update failed: ${response.status}`);
  }
  return response.json();
}

export async function duplicateSimulation(simulationId: string): Promise<Simulation> {
  const response = await fetch(`${apiBaseUrl}/api/v1/simulations/${encodeURIComponent(simulationId)}/duplicate`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({})
  });
  if (!response.ok) {
    throw new Error(`Simulation duplicate failed: ${response.status}`);
  }
  return response.json();
}

export async function deleteSimulation(simulationId: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/v1/simulations/${encodeURIComponent(simulationId)}`, {
    method: "DELETE"
  });
  if (!response.ok) {
    throw new Error(`Simulation delete failed: ${response.status}`);
  }
}

export async function runSimulation(simulationId: string): Promise<SimulationRun> {
  const response = await fetch(`${apiBaseUrl}/api/v1/simulations/${encodeURIComponent(simulationId)}/run`, {
    method: "POST"
  });
  if (!response.ok) {
    throw new Error(`Simulation run failed: ${response.status}`);
  }
  return response.json();
}

export async function listSimulationRuns(simulationId: string): Promise<RunListResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/simulations/${encodeURIComponent(simulationId)}/runs`);
  if (!response.ok) {
    throw new Error(`Simulation runs failed: ${response.status}`);
  }
  return response.json();
}

export async function pauseRun(runId: string): Promise<SimulationRun> {
  const response = await fetch(`${apiBaseUrl}/api/v1/runs/${encodeURIComponent(runId)}/pause`, {method: "POST"});
  if (!response.ok) {
    throw new Error(`Run pause failed: ${response.status}`);
  }
  return response.json();
}

export async function resumeRun(runId: string): Promise<SimulationRun> {
  const response = await fetch(`${apiBaseUrl}/api/v1/runs/${encodeURIComponent(runId)}/resume`, {method: "POST"});
  if (!response.ok) {
    throw new Error(`Run resume failed: ${response.status}`);
  }
  return response.json();
}

export async function stopRun(runId: string): Promise<SimulationRun> {
  const response = await fetch(`${apiBaseUrl}/api/v1/runs/${encodeURIComponent(runId)}/stop`, {method: "POST"});
  if (!response.ok) {
    throw new Error(`Run stop failed: ${response.status}`);
  }
  return response.json();
}

export async function setRunSpeed(runId: string, speedMultiplier: number): Promise<SimulationRun> {
  const response = await fetch(`${apiBaseUrl}/api/v1/runs/${encodeURIComponent(runId)}/speed`, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({speed_multiplier: speedMultiplier})
  });
  if (!response.ok) {
    throw new Error(`Run speed failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchRunResult(runId: string): Promise<RunResultResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/runs/${encodeURIComponent(runId)}/result`);
  if (!response.ok) {
    throw new Error(`Run result failed: ${response.status}`);
  }
  return response.json();
}
