> **DEPRECATED (2026-06-04):** The web stack was replaced by the pai_chatbot-derived
> Virtual Process LangGraph system. See [spec_virtual_process.md](spec_virtual_process.md).
> The design below describes the prior FastAPI+React chatbot and is kept for history only.

# Web System Specification

**Project:** VCORE — AI Twin Platform  
**Subsystem:** Web Backend (FastAPI) + Web Frontend (React)  
**Version:** 0.1 (Demo Prototype)

---

## 1. Overview

The web system provides:
- REST API for controlling UE5 simulation and retrieving results
- WebSocket relay between UE5 streamer and browser clients
- AI Scenario Agent (LLM chat) for scenario ideation and parameter generation
- KPI comparison dashboard
- Approval workflow with PDF report export

### Deployment (portfolio demo)

The web subsystem is exposed as a public demo at `v-core.yoosung.dev` via a single
Cloudflare Tunnel to the local `chat-web` nginx (`:5173`), which serves the static overlay
and same-origin reverse-proxies the backend (`:8000`). UE5, Ollama, and the backend run
locally. Full procedure: [deploy_cloudflare.md](deploy_cloudflare.md).

---

## 2. Backend — FastAPI

### 2.1 Directory Structure

```
web/backend/
├── app/
│   ├── main.py                  ← FastAPI app factory, router registration
│   ├── config.py                ← pydantic-settings config (reads .env)
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── simulation.py    ← /api/v1/simulation/* routes
│   │       ├── agent.py         ← /api/v1/agent/* routes (chat)
│   │       ├── reports.py       ← /api/v1/reports/* routes
│   │       └── internal/
│   │           └── ue5.py       ← /internal/ue5/* routes (UE5 inbound)
│   ├── services/
│   │   ├── simulation_service.py   ← Start/stop sim, relay to UE5
│   │   ├── kpi_service.py          ← KPI calculation from timeline logs
│   │   ├── report_service.py       ← LLM analysis, PDF generation
│   │   ├── ws_relay.py             ← WebSocket fan-out (UE5 → browsers)
│   │   └── agent/
│   │       ├── agent_executor.py   ← LangChain agent setup
│   │       ├── system_prompt.py    ← AGV domain system prompt
│   │       └── tools.py            ← Agent tool definitions
│   ├── models/
│   │   ├── base.py              ← SQLAlchemy declarative base
│   │   ├── scenario.py
│   │   ├── simulation_run.py
│   │   ├── kpi_result.py
│   │   ├── timeline_log.py
│   │   ├── llm_log.py
│   │   └── report.py
│   ├── schemas/
│   │   ├── simulation.py        ← Pydantic request/response models
│   │   ├── agent.py
│   │   ├── report.py
│   │   └── ue5_messages.py      ← Pydantic models for UE5 WebSocket messages
│   └── core/
│       ├── database.py          ← SQLAlchemy async engine + session
│       ├── redis_client.py      ← Redis connection (for pub/sub)
│       └── security.py          ← API key validation middleware
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
├── tests/
│   ├── conftest.py
│   ├── test_simulation.py
│   └── test_agent.py
├── Dockerfile
├── requirements.txt
└── .env.example
```

### 2.2 Environment Variables (`.env`)

```env
DATABASE_URL=postgresql+asyncpg://aicham:password@db:5432/aicham
REDIS_URL=redis://redis:6379/0
GEMINI_API_KEY=your-gemini-api-key
AGV_API_KEY=demo-api-key-change-in-prod
UE5_HOST=host.docker.internal
UE5_PORT=7777
SIMULATION_STALE_TIMEOUT_SEC=30
SECRET_KEY=change-me-in-prod
```

### 2.3 API Routes

#### Simulation Routes (`/api/v1/simulation/`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/simulation/start` | Create run record, send `Start_Sim` to UE5 |
| `GET` | `/api/v1/simulation/{run_id}` | Get run status and metadata |
| `GET` | `/api/v1/simulation/{run_id}/logs` | Get paginated timeline log entries |
| `POST` | `/api/v1/simulation/{run_id}/stop` | Stop the active run, ask UE5 to stop, and release the run lock |
| `GET` | `/api/v1/simulation/` | List all simulation runs |

#### Agent Routes (`/api/v1/agent/`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/agent/chat` | Send user message; returns SSE stream of LLM response tokens |
| `GET` | `/api/v1/agent/history/{session_id}` | Get chat history for session |

#### Report Routes (`/api/v1/reports/`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/reports/compare` | Compare two runs (query params: `baseline`, `modified`) |
| `POST` | `/api/v1/reports/{report_id}/analyze` | Trigger LLM analysis; returns Korean structured JSON |
| `GET` | `/api/v1/reports/{report_id}` | Get report with LLM analysis text |
| `POST` | `/api/v1/reports/{report_id}/decision` | Submit approve/hold/reject decision |
| `GET` | `/api/v1/reports/{report_id}/pdf` | Download PDF report |

#### Internal Routes (`/internal/ue5/`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/internal/ue5/simulation/{run_id}/complete` | UE5 submits final timeline + KPIs |
| `WS` | `/ws/ue5/stream/{run_id}` | UE5 streams real-time SimEvents |
| `WS` | `/ws/dashboard/{run_id}` | Browser subscribes to sim event feed |

> Internal routes are protected by `X-AGV-API-Key` header validation (not user-facing JWT).

### 2.4 Database Schema

```sql
-- scenarios: named parameter sets for simulation
CREATE TABLE scenarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    parameters_json JSONB NOT NULL,   -- {speed, duration, policy_id, ...}
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- simulation_runs: one execution instance
CREATE TABLE simulation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id UUID REFERENCES scenarios(id),
    status TEXT NOT NULL DEFAULT 'pending',   -- pending|running|completed|stopped|error
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- kpi_results: computed after run completion
CREATE TABLE kpi_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES simulation_runs(id) UNIQUE,
    throughput FLOAT,          -- tasks/simulated_hour
    avg_wait_time FLOAT,       -- seconds (simulated)
    collision_risk FLOAT,      -- collisions/simulated_hour
    uptime FLOAT,              -- 0.0 - 1.0
    raw_json JSONB,            -- full raw data from UE5
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- timeline_logs: individual events from UE5
CREATE TABLE timeline_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID REFERENCES simulation_runs(id),
    sim_timestamp FLOAT NOT NULL,    -- simulated seconds from run start
    event_type TEXT NOT NULL,        -- AGV_STATE_CHANGE|COLLISION|BOTTLENECK|TASK_COMPLETE
    agv_id TEXT,
    data_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_timeline_logs_run_id ON timeline_logs(run_id);

-- llm_logs: all LLM calls for debugging
CREATE TABLE llm_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_json JSONB,
    response_json JSONB,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- reports: comparison + decision record
CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES simulation_runs(id),
    baseline_run_id UUID REFERENCES simulation_runs(id),
    llm_analysis TEXT,
    status TEXT DEFAULT 'pending',   -- pending|analyzing|ready|approved|held|rejected
    decision_notes TEXT,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    pdf_path TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2.5 WebSocket Fan-out Architecture

```
UE5 ──WS──> /ws/ue5/stream/{run_id}
                    │
            ws_relay.py  (asyncio task per run_id)
                    │
             Redis Pub/Sub channel: sim:{run_id}
                    │
            /ws/dashboard/{run_id}
                    │
         Browser 1, Browser 2, ...
```

- `ws_relay.py` subscribes to Redis channel on first UE5 connection for a `run_id`.
- Dashboard WebSocket handler subscribes to the same Redis channel and forwards to browser.
- This allows multiple browser clients to receive the same sim stream.

### 2.6 Demo Recovery Rules

- The backend treats `running` rows as a demo lock and blocks a second start request while one is active.
- Before creating a new run, the backend automatically marks stale `running` rows as `error` once they are older than the demo timeout window.
- `POST /api/v1/simulation/{run_id}/stop` marks the run as `stopped`, publishes a `RunComplete` message, and attempts to call UE5 `POST /sim/stop`.
- UE5 also includes a fallback auto-complete timer so a demo run does not stay locked forever if the AGV gameplay loop has not been implemented yet.

### 2.7 AI Scenario Agent

**Model:** `gemini-2.0-flash` (via `langchain-google-genai`)

**Agent Tools:**

| Tool | Description |
|---|---|
| `get_current_kpis(run_id)` | Fetches KPI data for the most recent completed run |
| `list_scenarios()` | Returns named scenarios and their parameters |
| `propose_scenario(params)` | Creates a new scenario record and returns its ID |
| `start_simulation(scenario_id)` | Sends Start_Sim command; returns run_id |

**System Prompt (in `services/agent/system_prompt.py`):**
```
You are an industrial operations AI assistant for an AGV (Automated Guided Vehicle) 
factory cell simulation platform. You help operations managers design and evaluate 
changes to AGV routing policies, speed parameters, and fleet configurations.

When the user describes a goal (e.g., "increase throughput by 10%"), you should:
1. Retrieve current KPI data using get_current_kpis.
2. Analyze current bottlenecks and constraints.
3. Propose specific parameter changes with expected impact reasoning.
4. Ask for user confirmation before starting a simulation.
5. After simulation, summarize results against the stated goal.

Always reason quantitatively. Cite KPI values. Be concise.
```

**Streaming:** Agent responses stream via Server-Sent Events (SSE) from `POST /api/v1/agent/chat`.

---

## 3. Frontend — React

### 3.1 Directory Structure

```
web/frontend/
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── pages/
│   │   ├── DashboardPage.tsx    ← layout with sidebar nav
│   │   ├── ChatPage.tsx         ← AI scenario agent chat
│   │   ├── SimulationPage.tsx   ← real-time monitoring
│   │   ├── ComparePage.tsx      ← baseline vs. modified comparison
│   │   └── ReportPage.tsx       ← LLM report + approval workflow
│   ├── components/
│   │   ├── chat/
│   │   │   ├── ChatPanel.tsx
│   │   │   └── MessageBubble.tsx
│   │   ├── simulation/
│   │   │   ├── SimProgressBar.tsx
│   │   │   ├── EventLogFeed.tsx
│   │   │   └── KPIGauges.tsx
│   │   ├── compare/
│   │   │   ├── KPICompareChart.tsx
│   │   │   └── KPISummaryTable.tsx
│   │   └── report/
│   │       ├── LLMAnalysisPanel.tsx
│   │       └── DecisionPanel.tsx
│   ├── hooks/
│   │   ├── useSimulationWS.ts   ← WebSocket hook for sim events
│   │   └── useSSEChat.ts        ← SSE hook for agent streaming
│   ├── api/
│   │   ├── client.ts            ← axios instance with base URL
│   │   ├── simulation.ts
│   │   ├── agent.ts
│   │   └── reports.ts
│   ├── store/
│   │   └── simStore.ts          ← zustand store for active sim state
│   └── types/
│       └── index.ts             ← shared TypeScript types
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
└── Dockerfile
```

### 3.2 Key Dependencies

```json
{
  "dependencies": {
    "react": "^18",
    "react-router-dom": "^6",
    "@tanstack/react-query": "^5",
    "zustand": "^4",
    "axios": "^1",
    "recharts": "^2",
    "dompurify": "^3"
  }
}
```

### 3.3 Page Specifications

#### ChatPage (`/chat`)
- Split panel: left = chat history, right = current KPI summary cards.
- Input box at bottom; send on Enter or click.
- SSE stream renders tokens as they arrive (typewriter effect).
- "Run Simulation" button appears when agent calls `propose_scenario` tool.
- Clicking confirms and calls `start_simulation`; navigates to SimulationPage.

#### SimulationPage (`/simulation/:runId`)
- Progress bar: 0–100% based on `elapsed / duration` from WebSocket messages.
- Event log: scrolling list, newest at bottom, color-coded by event type.
  - `AGV_STATE_CHANGE` — gray
  - `TASK_COMPLETE` — green
  - `BOTTLENECK` — orange
  - `COLLISION` — red
- KPI gauges: 4 live updating number displays (throughput, wait, collision risk, uptime).
- [Stop Simulation] button → calls `POST /api/v1/simulation/{runId}/stop`.

#### ComparePage (`/compare`)
- [AI로 분석하기] button calls `POST /api/v1/reports/{reportId}/analyze`.
- Analysis response JSON contains Korean user-facing text for `summary`, `improvements`, `concerns`, and `recommendation`.
- Run selector: dropdown for Baseline run, dropdown for Modified run.
- KPI bar chart: grouped bars for each of 4 KPIs.
- Delta table: KPI | Baseline | Modified | Change | % Change (color: green if improved, red if worsened).
- [Generate Report] button → calls `POST /api/v1/reports/{runId}/analyze`.

#### ReportPage (`/report/:reportId`)
- Korean LLM analysis text displayed as formatted markdown.
- Decision panel: 3 buttons [Approve] [Hold] [Reject] + notes textarea.
- On approve: status badge changes to "Final Plan"; [Download PDF] button appears.
- PDF download: `GET /api/v1/reports/{reportId}/pdf` → file download.

---

## 4. PDF Report Structure

Generated by WeasyPrint from an HTML/CSS template.

| Section | Content |
|---|---|
| Cover | Project name, scenario name, date, decision status |
| Executive Summary | LLM-generated 2-paragraph summary |
| KPI Comparison Table | 4 KPIs × Baseline + Modified + Delta |
| Timeline Highlights | Top 5 notable events (collisions, worst bottlenecks) |
| Decision Record | Approver name, date, notes |
| Appendix | Full event count breakdown by type |
