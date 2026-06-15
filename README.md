# VCORE — Virtual Process AI Twin Platform

VCORE is an **AI Twin Platform for pre-verification of industrial operational strategies**.
A natural-language request to an AI chatbot is turned into safe, schema-validated commands
that drive a **UE5 AGV cell simulation** ("Virtual Process"), with progress and KPIs
streaming back to the chat in real time.

It has two subsystems:

- **Unreal Engine 5 (`Source/VCORE`)** — a 3D AGV cell simulation. `AGVSimController`
  exposes an HTTP control server on `:7777` and emits chat-correlated events.
- **Web (`web/`)** — a LangGraph multi-agent chatbot (FastAPI + Ollama/Gemma) with a
  React/Vite WebView overlay UI that talks to UE5.

> **2026-06-04 migration:** the web stack was replaced by the pai_chatbot-derived
> **Virtual Process** system (rebranded from "Smart Farm", `bed` → `station`). Full design:
> [docs/spec_virtual_process.md](docs/spec_virtual_process.md).

---

## Architecture

```
chat-web (React/Vite WebView)
        │  POST /chat/messages · WS /chat/sessions/{id}/events
        ▼
chatbot-backend (FastAPI + LangGraph multi-agent, Ollama/Gemma)
   ├─ ChatOrchestrator → LangGraphMultiResponseAgent graph
   ├─ control-server-demo  ── station registry (/cell/status, /stations/{id})
   └─ Ue5CommandClient ───────► UE5 AGVSimController :7777
                                   /sim/start|stop|pause|resume|speed
                                   /agv/command · GET /sim/status
        ▲  POST /internal/ue5/events  (UE5 → backend chat-correlated events)
        └──────────────────────────────── UE5
```

### Services (`web/services/`)

| Service | Role | Port |
|---|---|---|
| `chatbot-backend` | LangGraph orchestration, Ollama LLM gateway, UE5 driver, event ingest | 8000 |
| `chat-web` | React/Vite WebView overlay (chat + process dashboard + zone focus) | 5173/5199 |
| `control-server-demo` | Station registry mock | 8010 |
| `telemetry-collector` | UE5 telemetry (UDP/TCP/WS) → Firebase RTDB ingest | 9999/9998 |
| `iot-platform-demo` | Legacy IoT mock — **orphaned**, `legacy` profile only (`--profile legacy`) | 8020 |
| `ollama` / `ollama-model` | Local Gemma runtime + model pull | 11434 |
| postgres / redis / qdrant / timescaledb | Data stores (session/command + optional RAG/timeseries) | — |
| `data-seeder` | Optional DB seeding — `tools` profile only (`--profile tools`) | — |

### Agent command set

- **Station-targeted:** `run_station_task`, `move_to_station`, `inspect_station`, `cancel_command`
- **Sim lifecycle (Virtual Process control):** `start_simulation`, `stop_simulation`,
  `pause_simulation`, `resume_simulation`, `set_sim_speed`

### Domain model

- `Station` (`station_id`, `station_type`, `task_ready`, `cell_id`, `zone`, `state`, `accessible`)
- `ProcessTelemetry` (`throughput`, `active_agvs`, `avg_wait_time`, `collision_risk`, `uptime`)

---

## Running the demo

Requires Docker (+ GPU for Ollama). UE5 changes require the Unreal editor.

```sh
cd web
cp .env.example .env          # set UE5_CLIENT_MODE=ue5 + AGV_API_KEY to drive real UE5
docker compose up --build     # wait for chatbot-backend healthy + ollama-model pulled
```

> **SFT tool-router (`LLM_PROVIDER=routing_split`):** when `web/.env` selects the fine-tuned router,
> tool calls are served by a **host** `llama-server` on `:8080` (`docs/sft/data/vcore-toolrouter.gguf`,
> a Windows CUDA build) that compose does **not** start. Use the helper instead of a bare compose up —
> it launches the host server (idempotently) then `docker compose up -d`:
> ```powershell
> ./start-router.ps1            # router (:8080) + full stack;  -RouterOnly for just the router
> ```
> Verify with `GET http://localhost:8000/llm/status` → `status: ready`. Plain `ollama` provider needs
> no host server and runs with `docker compose up` alone.

- Backend health: `GET http://localhost:8000/health`
- Overlay dashboard: `GET http://localhost:8000/dashboard/overlay`
- Open `chat-web` (`:5173`/`:5199`) and try (Korean):
  - "공정 상태 알려줘" → process telemetry
  - "2번 스테이션 작업해" → `run_station_task`
  - "시뮬레이션 시작 / 정지 / 일시정지", "속도 1.5배" → sim lifecycle

### UE5 ↔ backend

1. **Compile `AGVSimController`** in the UE editor / Rider.
2. Ensure the UE editor `Config` `[AGVSim] APIKey` matches `AGV_API_KEY` in `web/.env`
   (used to authenticate the `/internal/ue5/events` ingest webhook).
3. Start PIE (HTTP server on `:7777`). Issue start/pause/resume/speed/stop and a
   `move_to_station` from chat; confirm events stream into the chat-web session and
   `GET :7777/sim/status` returns live KPIs.

### Tests (in Docker — no local Python)

```sh
docker compose exec chatbot-backend python -m pytest      # add pytest to the image if missing
```

---

## Repository layout

```
VCORE/
├── Source/VCORE/        ← UE5 C++ (AGVSimController + AGV cell actors; + unused template variants — see Legacy)
├── web/
│   ├── services/         ← chatbot-backend, chat-web, control-server-demo, telemetry-collector, iot-platform-demo, data-seeder
│   ├── infra/            ← postgres/ollama/qdrant/timeseries init
│   ├── secrets/          ← Firebase service account (gitignored)
│   ├── docs_pai/         ← upstream pai_chatbot docs (reference only — see Legacy)
│   └── docker-compose.yml
├── docs/                 ← spec_virtual_process.md + spec_unreal_architecture.md (current) + legacy specs (deprecated banners)
├── CLAUDE.md             ← agent rules + tech stack
├── PLAN.md               ← task plan + phase status
└── DONE.md               ← completed-feature summary
```

## Documentation

- [docs/spec_virtual_process.md](docs/spec_virtual_process.md) — current web↔UE5 architecture, endpoints, config
- [docs/spec_unreal.md](docs/spec_unreal.md) — UE5 simulation (with Virtual Process control routes)
- [docs/spec_unreal_architecture.md](docs/spec_unreal_architecture.md) — **UE5 directory partitioning + architecture plan** (refactor roadmap)
- [docs/PROJECT_IDEA.md](docs/PROJECT_IDEA.md) — vision document
- [web/README.md](web/README.md) — web workspace quick start

## Legacy / not wired to the current service

Content kept in-tree but **not connected** to the running Virtual Process demo. Audited 2026-06-07:

| Item | Verdict |
|---|---|
| `Source/VCORE/Variant_Strategy/` + `Content/Variant_Strategy/` | UE5 template leftover. **Removed 2026-06-07** (source, content, external actors/objects, `Build.cs` include paths). |
| `Source/docs/` | Stale mirror of `docs/` (files had diverged). **Removed 2026-06-07** — single source of truth is `docs/`. |
| TopDown GameMode chain: `VCOREGameMode/Character/PlayerController.*` + `Content/TopDown/` | Template boilerplate; Warehouse scene has no GameMode override. **Removed 2026-06-07**; empty `Content/TopDown/` shell cleaned 2026-06-09. |
| `Source/VCORE/Variant_TwinStick/` + `LVL_TwinStick` external actor/object data | UE5 template leftovers, unreferenced by the AGV sim. **Removed 2026-06-09**; `GlobalDefaultGameMode` now points at `/Script/VCORE.VirtualProcessGameMode`. |
| `docs/spec_api.md`, `spec_web.md`, `spec_directory.md` | Pre-migration specs (deprecation banners present). **Keep for history;** superseded by `spec_virtual_process.md` + `spec_unreal_architecture.md`. |
| `web/services/iot-platform-demo` | IoT mock; backend drives UE5 directly. **Orphaned** and now gated behind the `legacy` compose profile (`--profile legacy`). |
| `web/services/data-seeder` | Seeds the old DB schema. Gated behind the `tools` profile (does not run by default). **Keep as on-demand tool.** |
| `web/docs_pai/` | Upstream pai_chatbot documentation. **Reference only** — not part of this build. |
| `web/ARCHITECTURE.md`, `PROPOSAL.md`, `TECKSTACK.md` | pai-derived planning docs. **Reference only.** |

## Known follow-ups

- Verify end-to-end in Docker (Ollama/GPU) and UE PIE on the dev machine.
- `/agv/command` surfaces lifecycle events but does not yet retarget a spawned AGV to the
  station anchor (TODO in `AGVSimController::HandleAgvCommandRequest`).
- UE5 WebSocket client is repointed to `WS /internal/ue5/stream` for chat-correlated events
  and `TelemetryTransport=ws` live telemetry; old `/ws/ue5/stream/{run_id}` remains only in
  pre-migration reference docs.
- KPI compare / LLM report / approval / PDF from the old web stack were dropped — rebuild if needed.
- Partition `Source/VCORE` and decompose the 1622-line `AGVSimController` God Class — see
  [docs/spec_unreal_architecture.md](docs/spec_unreal_architecture.md) (phased P0–P4 roadmap).
