# LLM orchestration

## Runtime default

The demo runtime uses real Ollama inference by default:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=gemma4:e2b
OLLAMA_IMAGE_TAG=0.20.0
NVIDIA_VISIBLE_DEVICES=all
NVIDIA_DRIVER_CAPABILITIES=compute,utility
OLLAMA_TIMEOUT_SECONDS=120
```

Docker Compose starts the `ollama` service by default and runs `ollama-model` to
pull the configured model before `chatbot-backend` starts. The `ollama` service
requests all available NVIDIA GPUs with Compose `gpus: all`, so CUDA-capable
developer machines can run real inference without falling back to CPU. Use
`LLM_PROVIDER=rule_based` only for unit tests or constrained CI runs that
intentionally avoid real inference.

## Gateway contract

`LlmGateway` exposes three LLM-backed operations:

- `generate_plan_steps()`: selects a visible operational plan for the request.
- `propose_tool_call()`: chooses a tool call and arguments using the Ollama tool schema.
- `generate_report()`: writes the final user-facing completion or failure report.

`OllamaLlmGateway` calls `/api/chat` for all three operations with `think: false`
so thinking-capable models place structured output in `message.content` instead
of consuming the response budget in the thinking field. `RuleBasedLlmGateway` is
retained as a deterministic adapter for tests.

## LangGraph multi-response workflow

`ChatOrchestrator` delegates user-message handling to
`LangGraphMultiResponseAgent`. The graph is intentionally stateful but
interface-first:

- `record_user_message`: persists the user message and publishes `chat.message.received`.
- `publish_agent_plan`: calls the planning agent and publishes `agent.plan.*` events.
- `classify_request`: routes sensor, capability, and robot-command requests.
- `report_sensor_status` / `report_available_actions`: return non-command responses.
- `resolve_bed`: queries the control-server boundary for bed context.
- `plan_tool_call`: asks the configured `LlmGateway` for a tool call.
- `finalize_robot_command`: validates the tool contract, issues the command, and optionally publishes demo completion/report events.

Multiple logical agents can share a single loaded Ollama model because the graph
uses one `LlmGateway` instance and changes behavior through prompts, tools, and
node responsibilities rather than separate model processes.

Graph execution is invoked with a LangGraph `thread_id` derived from the chat
`session_id` and request `correlation_id`, and the compiled graph receives a
checkpointer. The current implementation uses LangGraph's in-process memory
checkpointer, while durable business state remains in the session repository.
This is sufficient for the single-process demo and leaves a direct replacement
point for a durable checkpoint backend.

For `propose_tool_call()`, Ollama remains the primary planner. If Ollama returns
an empty, non-tool, non-parseable, or contract-invalid tool response for a clearly
supported demo command, the gateway applies the same deterministic rule-based
parser used by tests. This keeps the chat flow functional for Korean and English
demo commands without bypassing the LLM boundary or changing the tool contract.

## Visible plan selection

The user-facing `agent.plan.*` event stream is generated from
`generate_plan_steps()`. Ollama receives the user request and chooses from these
routes:

- `sensor_status`
- `robot_harvest`
- `robot_move`
- `robot_inspect`
- `robot_cancel`
- `ambiguous`

The model returns JSON:

```json
{"steps":["요청 의도를 분류합니다.","수확 플랜을 선택합니다.","도구 호출을 검증합니다."]}
```

The backend publishes the returned steps as `agent.plan.started`,
`agent.plan.step`, and `agent.plan.completed`. If Ollama is unavailable, the
plan event source is marked as `fallback`, and the normal LLM failure policy
handles the later tool/report stage.

## Prompt templates

Prompt templates live in `services/chatbot-backend/app/prompts/templates`:

- `plan_system.txt`
- `plan_user.txt`
- `tool_planning_system.txt`
- `tool_planning_user.txt`
- `report_system.txt`
- `report_user.txt`

## Tool contracts

Tool schemas are defined in `services/chatbot-backend/app/tools/contracts.py`
and exported to Ollama as native function tools:

- `harvest_bed`
- `move_to_bed`
- `inspect_bed`
- `cancel_robot_command`
