# CLAUDE.md — Agent Rules for VCORE Project

## Project Overview

VCORE is an **AI Twin Platform for Pre-verification of Industrial Operational Strategies**.
It consists of two subsystems:
- **Unreal Engine 5 (UE5)** — 3D AGV cell simulation with real-time event detection and KPI logging.
- **Web Dashboard** — FastAPI backend + React frontend with AI scenario agent, real-time monitoring, comparison reports, and approval workflow.

See [PROJECT_IDEA.md](PROJECT_IDEA.md) for the full vision document.

---

## Mandatory Workflow Rules

### 1. Session Start — Read These Files First
1. Read [PLAN.md](PLAN.md) — pending tasks and current phase status.
2. Consult [DONE.md](DONE.md) if you need detail on what has already been implemented.

### 2. Task Completion — Update These Files
After completing any task:
1. Update [DONE.md](DONE.md) — add a concise feature summary under the relevant phase (no log format; prose or bullet list describing what was built).
2. Mark the task `[x]` in [PLAN.md](PLAN.md); remove it if it has no remaining sub-tasks.

### 3. Documentation First
- For any non-trivial feature, update the relevant spec doc **before** writing code:
  - Unreal changes → [docs/spec_unreal.md](docs/spec_unreal.md)
  - Web/backend changes → [docs/spec_web.md](docs/spec_web.md)
  - API changes → [docs/spec_api.md](docs/spec_api.md)

---

## Architecture Constraints

### This is a Demo Prototype
- **Speed over scalability.** Implement the simplest thing that works end-to-end.
- No premature abstraction. No over-engineering. No features not in scope.
- Hardcode configuration values if needed for demo speed; mark with `# TODO: config` comment.

### Tech Stack (non-negotiable for demo)
> **Updated 2026-06-04:** the web stack was migrated to the pai_chatbot-derived
> **Virtual Process** LangGraph chatbot. See [docs/spec_virtual_process.md](docs/spec_virtual_process.md).
| Layer | Technology |
|---|---|
| Simulation | Unreal Engine 5 (C++) — `AGVSimController` drives the AGV cell + Virtual Process control routes |
| Backend | Python / FastAPI (DDD/hexagonal, `web/services/chatbot-backend`) |
| Frontend | React + Vite WebView overlay (`web/services/chat-web`) |
| AI Agent | LangGraph multi-agent + Ollama/Gemma (local LLM) |
| Station registry | `web/services/control-server-demo` (FastAPI mock) |
| Database | PostgreSQL (sessions/commands) + Redis; Qdrant/TimescaleDB optional |
| Infra | Docker Compose (`web/docker-compose.yml`, local demo) |

### Monorepo Structure
```
VCORE/
├── Source/VCORE/   ← UE5 C++ (AGVSimController + AGV cell actors)
├── web/
│   ├── services/    ← chatbot-backend, chat-web, control-server-demo, iot-platform-demo, data-seeder
│   ├── infra/       ← postgres/ollama/qdrant/timeseries init
│   └── docker-compose.yml
├── docs/            ← spec_virtual_process.md (current) + legacy specs (deprecation banners)
├── README.md        ← Top-level overview + run instructions
├── CLAUDE.md        ← This file
├── PLAN.md
├── DONE.md
├── AGENT.md
```

### Virtual Process Architecture (current web subsystem)
The web stack is a **LangGraph multi-agent chatbot** that drives the UE5 AGV cell:
- `chatbot-backend` (`web/services/chatbot-backend`): DDD/hexagonal FastAPI. The chat
  lifecycle runs as a LangGraph state machine (`application/multi_response_graph.py`); the
  LLM boundary is `OllamaLlmGateway`; `Ue5CommandClient` posts agent commands to the UE5
  HTTP server on `:7777`; UE5 events return via `interfaces/ue5_ingest.py`.
- Domain: `Station` (was `bed`), `ProcessTelemetry` (was sensor snapshot). Commands:
  `run_station_task`/`move_to_station`/`inspect_station`/`cancel_command` +
  `start_simulation`/`stop_simulation`/`pause_simulation`/`resume_simulation`/`set_sim_speed`.
- `chat-web` (`web/services/chat-web`): React/Vite WebView overlay (chat + process dashboard).
- `control-server-demo`: station registry mock (`/cell/status`, `/stations/{id}`).
- Full detail: [docs/spec_virtual_process.md](docs/spec_virtual_process.md). Run: [README.md](README.md).
- **Env note:** host Python is available (`C:/Users/PC/anaconda3/python.exe`) and is used for
  scripts, benchmarks, SFT data/training, and eval. The full backend *stack*
  (postgres/redis/ollama) still runs in Docker, but Python tooling does not require it. The
  backend `AGV_API_KEY` must match the UE editor's `[AGVSim] APIKey` for event ingest auth.

### LLM model & serving (READ before any LLM/benchmark/SFT work)
- **Production / benchmarked model: Ollama `qwen3.5:2b`** — one GGUF blob
  `sha256-b709d81508a078a686961de6ca07a953b895d9b286c46e17f00fb267f4f2d297` (2.74 GB).
  - Blob: `C:/Users/PC/.ollama/models/blobs/sha256-b709d815…`
  - Manifest: `C:/Users/PC/.ollama/models/manifests/registry.ollama.ai/library/qwen3.5/2b`
  - Note: `config.py` default tag is `qwen3.5:0.8b`, but all Phase-2/2-B benchmarks and the
    deployed path use **`qwen3.5:2b`** (set `OLLAMA_MODEL=qwen3.5:2b`). SFT targets this base.
- **Ollama serving:** `:11434`, `qwen3.5:2b`, reasoning off (`think:false`), `num_ctx 2048`.
- **llama.cpp serving (project binary, the reasoning-off lever):** version **9559 (`715b86a36`)**
  at `Intermediate/llama-build/bin/Release/llama-server.exe` — a CUDA build (`GGML_CUDA=ON`).
  Serve the same blob on `:8080`:
  ```
  Intermediate/llama-build/bin/Release/llama-server.exe \
    -m C:/Users/PC/.ollama/models/blobs/sha256-b709d81508a078a686961de6ca07a953b895d9b286c46e17f00fb267f4f2d297 \
    --host 0.0.0.0 --port 8080 -ngl 99 -c 8192 --jinja --reasoning off --reasoning-budget 0
  ```
  This is the Phase-2-B baseline regime (disambiguation 91.7%, KPI 94%). Do **not** rebuild
  this binary CPU-only (`GGML_CUDA=OFF`) — that regresses latency ~11.7s→~2.4s the wrong way.
- Benchmarks run on host anaconda python, not Docker:
  `scripts/benchmark_v2.py --providers ollama,llama_cpp --layers off,on --repeats 5`.

### Phase 3 — LLM SFT (Domain Tool Routing)
Active LLM work track: LoRA fine-tune the **production base `Qwen/Qwen3.5-2B`** (= `qwen3.5:2b`,
above) — same checkpoint as deployed so the v2 before/after comparison stays valid — to
internalize V-CORE tool routing so accurate `{"name","arguments"}` control JSON is produced
under a **minimal** prompt (reducing dependence on the long `tool_planning_system.txt`). Plan +
checklist: [docs/sft/plan.md](docs/sft/plan.md). Dataset (450 rows, labels grounded on the 9
real `tools/contracts.py` tools and validated against the live `ToolRouter`) lives in
`docs/sft/data/`. SFT-1 (data) is complete; SFT-2 (LoRA training, host Python + GPU); SFT-3 eval
harness `docs/sft/scripts/eval_sft.py` grades {Base+Full, Base+Minimal, SFT+Minimal}. Goal =
improve the production model + prove reduced long-prompt dependence (prod baseline 94% KPI /
91.7% disambiguation).

---

## Coding Standards

### General
- No unnecessary comments. Add a comment only when the **why** is non-obvious.
- No unused code. No backwards-compatibility shims.
- Validate only at system boundaries (user input, external API responses).

### Python / FastAPI
- Use `async def` for all route handlers.
- Pydantic models for all request/response bodies.
- Prefix internal routes with `/internal/`; public routes with `/api/v1/`.
- Never commit secrets. Use `.env` files; reference `config.py` via `pydantic-settings`.

### TypeScript / React
- Functional components only. No class components.
- Use `react-query` (TanStack Query) for server state.
- Use `zustand` for lightweight client state.

### UE5 / C++
- Follow Unreal naming conventions: `U` prefix for UObjects, `A` for AActor, `F` for structs.
- All WebSocket/HTTP communication logic lives in `public/AGVSimController` and `private/AGVSimController`.
- JSON serialization uses `FJsonObject` / `FJsonSerializer`.

---

## Security Rules
- Never expose internal DB IDs directly to the frontend — use UUIDs.
- Sanitize all LLM-generated content before rendering in React (use DOMPurify or equivalent).
- WebSocket messages from UE5 must be schema-validated on receipt by FastAPI.
- No SQL string concatenation — use SQLAlchemy ORM or parameterized queries only.

---

## Definition of "Done" for Each Task
A task is complete when:
1. Code works end-to-end in the demo scenario.
2. Relevant spec doc is updated.
3. [DONE.md](DONE.md) is updated with a feature summary.
4. [PLAN.md](PLAN.md) task is marked `[x]`.
