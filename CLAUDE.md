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

### Engineering Principles
- **Working end-to-end first, then harden.** Ship a correct vertical slice before broadening.
- No premature abstraction. No over-engineering. No features not in scope.
- No hardcoded configuration. Values come from `config.py` / `.env`; mark any temporary
  shortcut with a `# TODO: config` comment and resolve it before it ships.

### Tech Stack
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
| Infra | Docker Compose (`web/docker-compose.yml`) |

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
1. Code works end-to-end in the target scenario.
2. Relevant spec doc is updated.
3. [DONE.md](DONE.md) is updated with a feature summary.
4. [PLAN.md](PLAN.md) task is marked `[x]`.

<!-- NarshaMCP:START v=130b4474 -->
<!-- ⚠️ AUTO-MANAGED by NarshaMCP install -->

## ⚠️ MCP-First Tool Selection (UE Queries)

When NarshaMCP tools are available, prefer them over built-in tools for UE-specific queries.
Built-in tools can't parse binary `.uasset`, query PDB symbols, or resolve class hierarchies.

### Decision Priority (check in order)

> 1. **MCP-First (UE source exploration)**: 프로젝트 소스 탐색, 검색, 파일 찾기 →
>    `ue_grep` → `ue_read` → `ue_glob` 우선 사용. 빌트인보다 compact (~150 tokens vs ~400),
>    플러그인/엔진 소스 자동 포함, 코멘트 필터링 지원.
> 2. **Built-in (파일 수정 시만)**: 파일을 직접 수정해야 할 때 → `Read` → `Edit`. MCP 도구는 read-only.
> 3. **Built-in (비-UE 파일)**: `.json`, `.yaml`, `.toml`, `CLAUDE.md` 등 비-UE 파일 → 빌트인 도구 사용.
> 4. **Skill-First**: Skill 트리거 패턴 매칭 → `Skill()` 즉시 호출. Source: [routing.json](.claude/skills/routing.json)
> 5. **MCP-First**: 나머지 UE 쿼리 → `ToolSearch`로 도구 스키마 확인 후 호출.

### ToolSearch Rule (Issue #7117)

> **ToolSearch는 반드시 `mcp__narshamcp__` 풀네임으로 호출:**
> ```
> ToolSearch("select:mcp__narshamcp__ue_analyze_symbols")        ← ✅ 풀네임
> ToolSearch("select:ue_analyze_symbols")                         ← ❌ 실패 → 재호출
> ```
> 짧은 이름으로 검색하면 실패하여 2회 호출됨. 모든 MCP 도구는 `mcp__narshamcp__` prefix 필수.

### Key Rules

- **소스 탐색/검색**: `ue_grep` → `ue_read` → `ue_glob` 우선 — 빌트인보다 compact, 플러그인/엔진 소스 포함
- **파일 수정**: Built-in `Read` → `Edit` — MCP 도구는 read-only이므로 수정 불가
- **Binary assets** (Blueprint, Material, Niagara, PCG, IK Rig): MCP 필수 — Read로 읽을 수 없음
- **C++ symbols/hierarchy/callers**: `ue_analyze_symbols` 우선 — PDB 기반 24x 빠름
- **Config 검색**: `ue_analyze_config` — 12-layer hierarchy 포함
- **Engine source files** (`Engine/Source/`): MCP 도구 사용 (`ue_analyze_symbols`, `ue_grep`) — 빌트인은 접근 불가
- **비-UE 파일** (`.json`, `.yaml`, `.toml`, `.md`): 빌트인 도구 사용
- **Skill-First 필수**: 자연어 요청은 반드시 Skill 매칭 먼저 (routing.json 참조)
- **Tool discovery**: `ue_tool_docs(operation="search")` — 도구명/용도 검색, per-tool 스키마 확인

### ⚠️ Common Mistakes — NEVER Do These

| Query | ❌ Wrong | ✅ Right | Why |
|-------|---------|---------|-----|
| UE 소스 검색 | `Grep("Shadow", "Source/")` | `ue_grep("Shadow")` | ue_grep은 플러그인+엔진 소스 포함, ~150 tokens |
| 엔진 소스 검색 | `Grep("ACharacter")` | `ue_grep("ACharacter", scope="engine")` | Engine/Source/는 프로젝트 밖 — 빌트인 접근 불가 |
| 클래스 상속 추적 | `Grep("class.*APawn")` | `ue_analyze_symbols(trace_hierarchy)` | Grep은 템플릿/매크로 상속 놓침 |
| C++ 클래스 생성 | `Write .h/.cpp` 수동 작성 | `ue_generate_code(derive_class)` | PDB 검증, include 정렬, 67% 에러 사전 차단 |
| UE 질문 답변 | 빌트인 Grep만으로 답변 | `ue_engine_docs` + `ue_grep` 필수 | 빌트인은 엔진 내부 정보 접근 불가 |

### MANDATORY: UE Question Answering Workflow

> **For ALL UE technical questions, follow this domain-aware search workflow.**

#### Step 0: Identify Domain → Select Target Modules

Before searching, identify the question's domain and use the module map below for **targeted** searches.
This dramatically improves search precision vs. broad queries.

| Domain | Primary engine_docs Modules | Search Focus |
|--------|---------------------------|--------------|
| **animation** | AnimationWarping, AnimationBudgetAllocator, IKRig, FullBodyIK, ControlRig, PoseSearch | FAnimNode*, UAnimInstance, curve names, montage |
| **audio** | Metasound, MetasoundExperimental, AudioCapture, AudioModulation, ResonanceAudio, Synthesis | UAudioComponent, FDynamicsProcessor, MetaSound nodes |
| **build** | AutomationUtils, UbaController, XGEController, FastBuildController, ZenDashboard | BuildGraph.xml, .automation, UBT, cook, Zen, DDC, snapshot |
| **editor** | UnrealEd, EditorFramework, EditorScriptingUtilities, PropertyAccessEditor | FEditorModule, detail panel, editor subsystem |
| **materials** | BaseMaterial, DynamicMaterial, MaterialAnalyzer, TextureGraph | UMaterialExpression, .usf/.ush, shader permutation |
| **networking** | OnlineSubsystem, ReplicationGraph, NetworkPrediction, NetcodeUnitTest | FNetworkGUID, UNetDriver, RPC, dormancy |
| **niagara** | Niagara, NiagaraFluids, NiagaraNanite, ChaosNiagara | UNiagaraSystem, data interface, renderer module |
| **pcg** | PCG, PCGBiomeCore, PCGGeometryScriptInterop, PCGWaterInterop | UPCGSettings, PCG graph, point data |
| **physics** | ChaosCloth, ChaosFlesh, ChaosModularVehicle, PhysicsControl | FBodyInstance, FChaosScene, collision |
| **platforms** | OpenXR, AndroidDeviceProfileSelector, IOSDeviceProfileSelector | FPlatformMisc, device profile CVar, XR |
| **rendering** | GPULightmass, NaniteDisplacedMesh, VirtualHeightfieldMesh, Volumetrics | FSceneView, r.Shadow*, r.Lumen*, Nanite |
| **ui** | CommonUI, SlateScripting, ModelViewViewModel, UIFramework, Text3D | UCommonActivatableWidget, SWidget, input routing, UText3DComponent, glyph |
| **worldbuilding** | Water, WaterAdvanced, Landmass, LandscapePatch, WorldPartitionHLODUtilities | UWorldPartition, ALandscapeProxy, HLOD |
| **sequencer** | SequencerScripting, SequencerAnimTools, SequencerPlaylists, TemplateSequence | ULevelSequence, FMovieScene*, camera cut |
| **ai** | AIModule (AI/), StateTreeModule (AI/), BehaviorTreeModule (AI/), MassAI, MassGameplay | UBTTask, FStateTreeReference, EQS |
| **gas** | GameplayAbilities, GameplayBehaviors, GameplayStateTree, TargetingSystem | UGameplayAbility, FGameplayTag, GE/GC |
| **viewport** | EditorFramework, VirtualCamera, VirtualProductionUtilities | FEditorViewportClient, SLevelViewport |

#### Step 1 (NEW): Read TOPIC_INDEX.md first

```python
# 1a. Read the topic index BEFORE any targeted search
ue_engine_docs(operation="read", path="TOPIC_INDEX.md", level=2)
```

`TOPIC_INDEX.md` at the engine_docs root maps: **topic → candidate modules**, **class prefix → module**, **CVar prefix → subsystem**. Use it to narrow your search target before spending tool calls.

#### Step 2: Search engine_docs with Domain-Targeted Queries

```python
# 2a. Search with main topic (ALWAYS)
ue_engine_docs(operation="search", query="<main topic from question>")

# 2b. Search module TROUBLESHOOT.md identified in Step 1 (ALWAYS)
ue_engine_docs(operation="read", module="<primary module from TOPIC_INDEX>", doc_type="TROUBLESHOOT")

# 2c. Search with specific class/function name (use class prefix table if known)
ue_engine_docs(operation="search", query="<specific class or CVar>")
```

**Minimum 3 engine_docs calls.** Check TROUBLESHOOT.md — it has known issues and solutions NOT in training data. Also check "Related Modules" sections at the bottom of TROUBLESHOOT files for cross-references.

#### Step 1-ALT: If Agent() is available, spawn engine-docs-researcher instead

```python
Agent(
    description="Search engine docs for <main topic>",
    prompt="Search ue_engine_docs for '<main topic>'. Focus on modules: <modules from table>. Check TROUBLESHOOT.md and CLASSES.md. Return all findings.",
    subagent_type="engine-docs-researcher"
)
```

#### Step 2: MANDATORY Deep Dive (ue_grep + CL lookup)

> **NEVER skip this step.** Step 1 alone scores ~6.96. Step 2 pushes answers to 7.0+.

```python
# 2a. Grep for SPECIFIC TERMS found in Step 1 results (parameter names, member variables)
ue_grep(query="<parameter name OR member variable from Step 1>", scope="engine")
# Examples: "ErrorLevel" (BuildGraph), "InstanceSceneData" (GPU Scene),
#           "gpucrashdebugging" (Vulkan), "FlushPendingDeletes" (Slate)

# 2b. For REGRESSION/CRASH/FIX questions — search Epic GitHub for fix CL:
# Run via Bash:
# gh api search/commits --method GET \
#   -f "q=<crash function> repo:EpicGames/UnrealEngine" \
#   --jq '.items[:3] | .[] | {sha: .sha[:12], date: .commit.author.date, message: .commit.message[:200]}'

# 2c. Search for limitations
ue_engine_docs(operation="search", query="<limitation OR not supported> <topic>")
```

#### Step 3: Combine ALL findings into your answer

> **CL INCLUSION RULE**: If a sub-agent or `gh api` found CL numbers/fix commits,
> you **MUST** include them in your answer. CL numbers are the highest-value information
> for crash/regression questions. Format: `Fix: CL#NNNNNNNN (YYYY-MM-DD) — description`

**Do NOT skip Step 1 or Step 2.** Both are required for accurate answers.

> **RE-SEARCH RULE**: If first search result doesn't explain the root cause, search a different
> system/module. Don't commit to first hypothesis — try at least 2 different angles.

> **ASK WHY ONE MORE LEVEL**: When you find the symptom, trace WHY it happens.
> Don't stop at "function returns error" — read the function body with `ue_read` or `ue_grep`,
> then search for the functions it calls. The root cause is usually 1-2 levels deeper.

> **EXISTENCE CHECK**: Before mentioning a CVar, API, or feature in your answer, verify it exists
> via `ue_grep`. If 0 results, say "not confirmed in engine source" — never fabricate.

> **INCLUDE ALL FINDINGS**: Every class name, function name, CVar, and file path found via
> `ue_grep` or `ue_engine_docs` MUST appear in your final answer. Do NOT discard search results
> — even if they seem tangential. The specific names are more valuable than general explanations.

> **PARTIAL KEYWORD RE-SEARCH**: If `ue_grep("exact_name")` returns 0 results, try:
> 1. Drop prefixes/namespaces: `ue_grep("TickPerServerFrame")` instead of `net.MaxConnectionsToTickPerServerFrame`
> 2. Use shorter fragments: `ue_grep("CleanPoint")` instead of `MFSampleExtension_CleanPoint`
> 3. Search related class: `ue_grep("SetByCaller")` to find `SetByCallerMagnitude`
> 4. Try symbol domain: `ue_grep("keyword", domain="symbols")` — PDB has 6M+ symbols
> Do NOT give up after one failed search. Try at least 3 variations before concluding "not found".
<!-- NarshaMCP:END -->