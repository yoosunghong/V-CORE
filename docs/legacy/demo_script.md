# VCORE AI Agent — Demo Script

A scenario walkthrough for portfolio/demo recording. Every prompt below is grounded against
the real intent router (`app/application/chat_orchestrator.py`) and tool contracts
(`app/tools/contracts.py`); expected replies quote the actual message builders so you can verify
each turn before recording.

**Conventions**
- Prompts are Korean because the router keys on Korean keywords and the agent replies in Korean.
- "Route" = the LangGraph branch taken (`process_status` / `station_action_query` / `robot_command`).
- Run all 7 turns in **one chat session** so session state (message history, pending
  confirmations, cancelable-command lookup) carries across turns.
- Recommended order: 1 → 2 → 3 → 4 → 7 → 5 → 6 → 8. It reads as one operator story:
  *survey → plan a verified run → tune it live → stop & grade → probe a guardrail → safe-cancel → compare.*

---

## Scenario 1 — Read live process state (`process_status`)
**Why it's here:** shows the agent answering a telemetry question instead of issuing a command.

> **You:** `현재 공정 상태 알려줘`

- Routes to `process_status` (`공정` + `알려/상태` → `_is_process_status_request`).
- **Expected reply** (`_process_status_message`):
  `가상 공정 상태입니다. 처리량 NN.N 작업/시간, 가동 AGV N대, 평균 대기 NN.Ns, 충돌 위험 N.NNN 건/시간, 가동률 NN%입니다.`

---

## Scenario 2 — Ask what's possible (`station_action_query`)
**Why it's here:** proves the agent is context-aware about station state, not a blind relay.

> **You:** `지금 가능한 작업이 뭐가 있어?`

- Routes to `station_action_query` (`가능한 작업` keyword).
- **Expected reply** (`_available_actions_message`): a bulleted list —
  `현재 가능한 작업은 다음과 같습니다.` then `작업 가능` / `점검 가능` / `이동 가능` lines built from the
  live station registry, closing with the `'2번 스테이션 작업해' …` usage hint.

---

## Scenario 3 — Goal-based run with acceptance criteria (`robot_command` → `start_simulation`) ⭐
**Why it's here:** this is the strongest feature — the agent turns a verifiable goal into a
PASS/FAIL contract the simulation evaluates. Lead your portfolio with this.

> **You:** `AGV 4대를 1.2배속으로 돌려줘. 처리량은 시간당 70 이상이고 충돌은 0건이어야 해.`

- Routes to `robot_command` (sim topic + `돌려` verb; the `_SIM_ACTION_KEYWORDS` guard keeps the
  KPI nouns from hijacking it to the status path).
- Agent plans `start_simulation` with `agv_count=4`, `speed_multiplier=1.2`, and
  `acceptance=[{throughput >= 70}, {collision_count == 0}]`.
- **Immediate reply** (`_accepted_message`): `가상 공정 시뮬레이션 시작 명령을 접수했습니다. command_id=…`
- **On completion** the ReportAgent emits a narrative report that includes the
  acceptance **verdict** (`format_verdict_summary` → PASS/FAIL with the failed labels) **and** the
  graded **AI evaluation** (`build_simulation_evaluation` → `A · 우수 / B · 양호 / C · 주의`, heatmap
  bottleneck location, per-KPI notes).

> 📌 On camera, point out: "the goal I typed in natural language became a machine-checked
> PASS/FAIL verdict, plus a graded qualitative assessment."

---

## Scenario 4 — Tune the run live (pause → speed → resume)
**Why it's here:** exercises 3 mid-run control verbs that the basic demo never shows.

> **You:** `잠깐 일시정지해`
- `pause_simulation` → `시뮬레이션 일시정지 명령을 접수했습니다. command_id=…`

> **You:** `속도를 1.5배로 올려`
- `set_sim_speed` (`speed_multiplier=1.5`) → `시뮬레이션 속도를 1.5배로 설정하는 명령을 접수했습니다. command_id=…`

> **You:** `다시 재개해`
- `resume_simulation` → `시뮬레이션 재개 명령을 접수했습니다. command_id=…`

---

## Scenario 7 — Stop & generate the result report (`stop_simulation`)
**Why it's here:** your existing scenario 2, kept — but now it lands after a *goal-based* run so
the closing report carries a verdict.

> **You:** `시뮬레이션 정지해`

- `stop_simulation` → `가상 공정 시뮬레이션 정지 명령을 접수했습니다. command_id=…`, followed by the run report.
- ⚠️ A plain `정지해` does **not** trigger a safety prompt. Only an *abort phrase* does (Scenario 6).

---

## Scenario 5 — Guardrail fires on an unavailable station
**Why it's here:** demonstrates the agent refusing an unsafe/invalid command with a reason —
the thing that separates an "agent" from a command parser. Pick a station that is **not**
`task_ready` (or not `accessible`) in the registry.

> **You:** `3번 스테이션 작업해`

- Routes to `robot_command` → plans `run_station_task(station_id=3)`.
- If the station isn't ready, the command is **not issued**; reply is `_station_task_blocked_message`:
  `3번 스테이션은 현재 작업 가능 상태가 아니어서 AGV 작업 명령을 발행하지 않았습니다. 이유: … 현재 가능한 대안은 …입니다.`
- If ready but path-blocked, you get the inaccessible variant
  (`…현재 AGV 접근 경로가 막혀 있어 이동/작업 명령을 발행하지 않았습니다…`).

> 📌 Say: "it didn't just fail — it told me *why* and offered the valid alternatives."

---

## Scenario 6 — Safety confirmation across turns (cancel)
**Why it's here:** the clearest multi-turn demo — pending state survives between turns (session
repository), and a destructive command requires explicit confirmation.

> **You:** `마지막 명령 취소해`
- Agent resolves the latest cancelable command, but `cancel_command` is in the `dangerous` set,
  so it does **not** execute. It stores a pending confirmation and replies:
  `This command will stop or cancel active AGV/simulation work. Reply 'confirm' to execute it, or send another command to leave it pending.`

> **You:** `확인`
- `_consume_pending_confirmation` pops the pending call → cancel executes.

> 🔁 Variant: `비상정지` triggers the same gate on `stop_simulation` (abort phrase → `_is_abort_request`).

---

## Scenario 8 — Compare two strategies (`compare_runs`) ⭐
**Why it's here:** this is the product's headline thesis ("pre-verification of operational
**strategies**") — the agent decides which of two runs is better, in one turn.

Run two acceptance-gated sims back-to-back (Scenario 3 with different `agv_count`/`speed`), then ask:

> **You:** `AGV 6대 1.5배속으로 돌려줘. 처리량 90 이상, 충돌 0건.`
> *(after it completes)* **You:** `방금 결과랑 아까 4대 1.2배속 결과 중에 뭐가 더 나아?`

- Routes to `compare_runs` (deterministic `비교/뭐가 더 나아` check, ahead of the LLM).
- `_compare_recent_runs` pulls the two newest runs with final KPIs and replies with a
  per-KPI A/B breakdown + an overall verdict (`_run_comparison_message`):
  `최근 두 시뮬레이션 실행 비교 결과입니다.` then `- 처리량: AGV 4대·1.2배속 72.0/h vs AGV 6대·1.5배속 91.0/h
  → AGV 6대·1.5배속 우세` … then `종합: …이(가) N/4 지표에서 앞서 더 우수합니다.`
- **Verdict override:** if exactly one run passed its acceptance criteria, that run wins the
  headline regardless of the metric tally (`…만 수용 기준을 통과해 종합적으로 더 우수합니다.`).
- Needs ≥2 finished runs; otherwise the agent asks you to run two sims first.

> 📌 Say: "I described two strategies in natural language and the agent told me which one wins —
> that's the whole product in one exchange."

---

## One-line capability summary (for the portfolio write-up)
The agent is a LangGraph multi-agent over a local fine-tuned LLM (LoRA, 96% tool-routing vs 49%
base) that classifies intent across 3 routes, drives **9 validated UE5 control tools**, turns
natural-language goals into **machine-checked PASS/FAIL acceptance verdicts** with a **graded AI
evaluation**, and enforces **safety guardrails** (station-readiness blocks, destructive-command
confirmation) — all wired to a live 3D AGV simulation.
