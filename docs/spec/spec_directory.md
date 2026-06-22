# Project Directory Structure

**Project:** VCORE — AI Twin Platform  
**Version:** 0.1 (Demo Prototype)

---

## Root Layout

```
VCORE/                          ← Project root (git repo root)
│
├── CLAUDE.md                    ← Agent rules (read every session)
├── AGENT.md                     ← Agent behavior specification
├── PLAN.md                      ← Implementation plan (update after every task)
├── NEXT_TASK_PROMPT.md          ← Current task context (rewrite after every session)
├── PROJECT_IDEA.md              ← Original concept document (read-only reference)
├── VCORE.uproject              ← UE5 project descriptor
├── VCORE.sln                   ← Visual Studio solution
│
├── Source/                      ← UE5 C++ source (Epic toolchain managed)
├── Content/                     ← UE5 assets (meshes, materials, maps, blueprints)
├── Config/                      ← UE5 configuration files
│
├── web/                         ← Web application (Docker Compose managed)
│
└── docs/                        ← All specification documents
```

---

## UE5 Source Tree (`Source/`)

```
Source/
├── VCORE.Target.cs             ← Game build target
├── VCOREEditor.Target.cs       ← Editor build target
└── VCORE/
    ├── VCORE.Build.cs          ← Module dependencies (add WebSockets, HTTP, Json)
    ├── VCORE.h / .cpp          ← Module entry point
    ├── VCOREGameMode.h / .cpp  ← Game mode (minimal for sim)
    │
    ├── public/                  ← Public headers (exposed to other modules)
    │   ├── AGVSimController.h       ← Main sim lifecycle actor
    │   ├── AGVActor.h               ← Individual AGV actor
    │   ├── SplinePathComponent.h    ← Spline follower component
    │   ├── IntersectionManager.h    ← Intersection priority logic
    │   ├── LoadingDockActor.h       ← Task generator actor
    │   ├── SimEventDispatcher.h     ← Event batching + WebSocket client
    │   └── KPIAccumulator.h         ← Raw counter accumulator
    │
    └── private/                 ← Implementation files
        ├── AGVSimController.cpp
        ├── AGVActor.cpp
        ├── SplinePathComponent.cpp
        ├── IntersectionManager.cpp
        ├── LoadingDockActor.cpp
        ├── SimEventDispatcher.cpp
        └── KPIAccumulator.cpp
```

**Rule:** All communication code (HTTP server, WebSocket client) lives in `AGVSimController` and `SimEventDispatcher`. Other classes have no network dependencies.

---

## UE5 Content Tree (`Content/`)

```
Content/
├── Maps/
│   └── AGVCell_Demo.umap        ← Main simulation map
├── Blueprints/
│   ├── BP_AGVActor              ← Blueprint child of AGVActor C++ class
│   ├── BP_LoadingDock           ← Blueprint child of LoadingDockActor
│   └── BP_SimController         ← Blueprint child of AGVSimController
├── Meshes/
│   ├── AGV_Body.uasset
│   ├── Cell_Floor.uasset
│   └── LoadingDock.uasset
├── Materials/
│   ├── M_AGV_Default.uasset
│   ├── M_AGV_Stopped.uasset     ← Red tint for collision-stopped state
│   └── M_AGV_Warning.uasset     ← Orange tint for bottleneck state
└── UI/
    ├── WBP_AGVStatusBar.uasset  ← Bottom HUD widget
    └── WBP_SimMetaPanel.uasset  ← Top-right metadata panel
```

---

## Web Application Tree (`web/`)

```
web/
├── docker-compose.yml           ← Orchestrates all web services
├── .env                         ← Local secrets (gitignored)
├── .env.example                 ← Template for .env
│
├── backend/                     ← FastAPI Python application
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env                     ← (symlink or copy from root .env)
│   │
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   │
│   ├── app/
│   │   ├── main.py              ← FastAPI app factory
│   │   ├── config.py            ← pydantic-settings
│   │   │
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── simulation.py
│   │   │       ├── agent.py
│   │   │       ├── reports.py
│   │   │       └── internal/
│   │   │           └── ue5.py   ← UE5 inbound endpoints
│   │   │
│   │   ├── services/
│   │   │   ├── simulation_service.py
│   │   │   ├── kpi_service.py
│   │   │   ├── report_service.py
│   │   │   ├── pdf_service.py
│   │   │   ├── ws_relay.py
│   │   │   └── agent/
│   │   │       ├── agent_executor.py
│   │   │       ├── system_prompt.py
│   │   │       └── tools.py
│   │   │
│   │   ├── models/
│   │   │   ├── base.py
│   │   │   ├── scenario.py
│   │   │   ├── simulation_run.py
│   │   │   ├── kpi_result.py
│   │   │   ├── timeline_log.py
│   │   │   ├── llm_log.py
│   │   │   └── report.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── simulation.py
│   │   │   ├── agent.py
│   │   │   ├── report.py
│   │   │   └── ue5_messages.py
│   │   │
│   │   └── core/
│   │       ├── database.py
│   │       ├── redis_client.py
│   │       └── security.py
│   │
│   └── tests/
│       ├── conftest.py
│       ├── test_simulation.py
│       ├── test_agent.py
│       └── test_reports.py
│
└── frontend/                    ← React + Vite + TypeScript
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    │
    └── src/
        ├── main.tsx
        ├── App.tsx
        │
        ├── pages/
        │   ├── DashboardPage.tsx    ← Shell layout with nav
        │   ├── ChatPage.tsx         ← AI scenario agent
        │   ├── SimulationPage.tsx   ← Real-time monitoring
        │   ├── ComparePage.tsx      ← KPI comparison
        │   └── ReportPage.tsx       ← Report + approval
        │
        ├── components/
        │   ├── chat/
        │   │   ├── ChatPanel.tsx
        │   │   └── MessageBubble.tsx
        │   ├── simulation/
        │   │   ├── SimProgressBar.tsx
        │   │   ├── EventLogFeed.tsx
        │   │   └── KPIGauges.tsx
        │   ├── compare/
        │   │   ├── KPICompareChart.tsx
        │   │   └── KPISummaryTable.tsx
        │   └── report/
        │       ├── LLMAnalysisPanel.tsx
        │       └── DecisionPanel.tsx
        │
        ├── hooks/
        │   ├── useSimulationWS.ts
        │   └── useSSEChat.ts
        │
        ├── api/
        │   ├── client.ts
        │   ├── simulation.ts
        │   ├── agent.ts
        │   └── reports.ts
        │
        ├── store/
        │   └── simStore.ts
        │
        └── types/
            └── index.ts
```

---

## Documentation Tree (`docs/`)

```
docs/
├── spec_unreal.md       ← UE5 simulation specification
├── spec_web.md          ← Web backend + frontend specification
├── spec_api.md          ← API exchange specification (UE5 ↔ Web)
├── spec_directory.md    ← This file — project directory layout
└── PROJECT_IDEA.md      ← Original concept (copy from root)
```

---

## Configuration Files (`Config/`)

```
Config/
├── DefaultEngine.ini
├── DefaultGame.ini      ← AGV sim config section:
│                           [AGVSim]
│                           BackendHost=localhost
│                           BackendPort=8000
│                           APIKey=demo-api-key-change-in-prod
│                           RunId=
└── DefaultInput.ini
```

---

## Gitignore Rules

```gitignore
# UE5
Binaries/
DerivedDataCache/
Intermediate/
Saved/
*.VC.db
*.VC.opendb

# Web
web/backend/.env
web/frontend/node_modules/
web/frontend/dist/
web/**/__pycache__/
web/**/*.pyc
web/backend/.venv/

# Secrets
.env
*.pem
*.key
```

---

## Public vs. Private API Boundary

| Category | Location | Access |
|---|---|---|
| User-facing API | `web/backend/app/api/v1/` | Public — no auth (demo) |
| UE5 inbound API | `web/backend/app/api/v1/internal/` | Protected by `X-AGV-API-Key` |
| UE5 HTTP server | `Source/VCORE/private/AGVSimController.cpp` | Local network only (localhost) |
| Database | PostgreSQL container | Backend service only (Docker network) |
| Redis | Redis container | Backend service only (Docker network) |
