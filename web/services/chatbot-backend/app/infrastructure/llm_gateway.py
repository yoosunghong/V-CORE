from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.agents.failure_policy import LlmGatewayError, LlmTimeoutError
from app.agents.llm_schemas import IntentDecision, PlanDecision, ToolCallDecision
from app.agents.planning_fallback import RuleBasedPlanningFallback
from app.domain.models import (
    DomainEvent,
    RetrievedChunk,
    RobotCommand,
    RobotCommandName,
    Station,
    ToolCall,
    format_verdict_summary,
)


def format_knowledge_block(chunks: list[RetrievedChunk] | None) -> str:
    """Render retrieved chunks into a numbered, citable prompt block (spec_rag.md §5.4).

    Returns "none" when there is nothing to ground on, so the prompt reads naturally and the
    model can fall back to its general behavior.
    """
    if not chunks:
        return "none"
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        text = chunk.text.strip().replace("\n", " ")
        if len(text) > 500:
            text = text[:500].rstrip() + "…"
        lines.append(f"[{index}] [출처: {chunk.title}] (source: {chunk.source})\n{text}")
    return "\n\n".join(lines)
from app.prompts.templates import PromptTemplateStore
from app.tools.contracts import ToolValidationError
from app.tools.router import ToolRouter


class OllamaLlmGateway:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 15.0,
        num_ctx: int = 2048,
        plan_num_predict: int = 192,
        tool_num_predict: int = 128,
        report_num_predict: int = 512,
        structured_retry_count: int = 1,
        prompt_store: PromptTemplateStore | None = None,
        tool_router: ToolRouter | None = None,
        enable_rule_based_fallback: bool = True,
        enable_argument_normalization: bool = False,
        enable_decline_retry: bool = False,
        enable_range_validation: bool = False,
        tool_system_template: str = "tool_planning_system",
        tool_user_template: str | None = "tool_planning_user",
        send_tool_schema: bool = True,
        adapter_scale: float | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._num_ctx = num_ctx
        self._plan_num_predict = plan_num_predict
        self._tool_num_predict = tool_num_predict
        self._report_num_predict = report_num_predict
        self._structured_retry_count = max(0, structured_retry_count)
        self._prompt_store = prompt_store or PromptTemplateStore()
        self._tool_router = tool_router or ToolRouter()
        # Phase-2 ablation toggles: flip the validation layer off (A1/B1) or on
        # (A2/B2) without changing the transport. structured_retry_count=0 also
        # disables the repair retry. The logic stays byte-identical across
        # providers because LlamaCppLlmGateway only overrides _post_chat.
        self._enable_rule_based_fallback = enable_rule_based_fallback
        self._enable_argument_normalization = enable_argument_normalization
        # Phase-2-B fixes (layer-ON only). Decline-retry lets the repair path reach a
        # valid "no tool / clarify" terminal state instead of coercing a call; range
        # validation rejects out-of-range argument values. Both default off so the
        # layer-OFF cells (A1/B1) reproduce the Phase-2-A intrinsic baseline exactly.
        self._enable_decline_retry = enable_decline_retry
        self._enable_range_validation = enable_range_validation
        # Routing-only SFT support: a model fine-tuned on the bare user command + a
        # minimal system prompt must be prompted the same way it was trained. These let
        # the routing gateway use the minimal system prompt, send the raw user command
        # (no tool_planning_user wrapper / station context), and skip the tool schema —
        # matching the eval that scored 96% — while the general gateway keeps its defaults.
        self._tool_system_template = tool_system_template
        self._tool_user_template = tool_user_template
        self._send_tool_schema = send_tool_schema
        # Adapter-toggle support: when set, llama.cpp requests carry a per-request LoRA
        # scale so one loaded base + routing adapter serves both tasks from a single
        # model in VRAM — scale 1.0 = SFT router, scale 0.0 = bare base for chat/report.
        # Unused by Ollama (its /api/chat has no per-request adapter control).
        self._adapter_scale = adapter_scale
        self.last_tool_attempts: list[dict[str, Any]] = []

    _VALID_INTENTS = {
        "process_status",
        "station_action_query",
        "robot_command",
        "knowledge_query",
        "general_chat",
    }

    async def preload(self, correlation_id: str = "startup-preload") -> None:
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "messages": [{"role": "user", "content": "preload"}],
            "options": self._options(temperature=0.0, num_predict=1),
            "keep_alive": "30m",
        }
        await self._post_chat(payload, correlation_id)

    async def classify_intent(
        self,
        user_message: str,
        correlation_id: str,
    ) -> str | None:
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": self._prompt_store.render("intent_system"),
                },
                {
                    "role": "user",
                    "content": self._prompt_store.render(
                        "intent_user",
                        user_message=user_message,
                    ),
                },
            ],
            "format": "json",
            "options": self._options(temperature=0.0, num_predict=24),
        }
        try:
            data = await self._post_chat(payload, correlation_id)
        except LlmGatewayError:
            return None
        content = (data.get("message", {}).get("content") or "").strip()
        if not content:
            return None
        try:
            parsed = self._parse_json_content(content)
        except LlmGatewayError:
            return None
        try:
            decision = IntentDecision.model_validate(
                {"intent": parsed.get("intent") or parsed.get("route")}
            )
        except Exception:
            return None
        return decision.intent if decision.intent in self._VALID_INTENTS else None

    async def generate_plan_steps(
        self,
        user_message: str,
        correlation_id: str,
    ) -> list[str]:
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": self._prompt_store.render("plan_system"),
                },
                {
                    "role": "user",
                    "content": self._prompt_store.render(
                        "plan_user",
                        user_message=user_message,
                    ),
                },
            ],
            "format": "json",
            "options": self._options(temperature=0.5, num_predict=self._plan_num_predict),
        }
        data = await self._post_chat(payload, correlation_id)
        return self._extract_plan_steps(data)

    async def propose_tool_call(
        self,
        user_message: str,
        station: Station | None,
        correlation_id: str,
    ) -> ToolCall | None:
        if self._tool_user_template is None:
            user_content = user_message
        else:
            user_content = self._prompt_store.render(
                self._tool_user_template,
                user_message=user_message,
                station_context=self._compact_station_context(station),
            )
        messages = [
            {
                "role": "system",
                "content": self._prompt_store.render(self._tool_system_template),
            },
            {"role": "user", "content": user_content},
        ]
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "messages": messages,
            "format": "json",
            "options": self._options(temperature=0.2, num_predict=self._tool_num_predict),
        }
        if self._send_tool_schema:
            payload["tools"] = self._tool_router.user_facing_tools()
        self.last_tool_attempts = []
        repair_hint = ""
        tool_call: ToolCall | None = None
        declined = False
        total_attempts = self._structured_retry_count + 1
        for attempt in range(total_attempts):
            attempt_payload = payload
            if attempt > 0:
                attempt_payload = {
                    **payload,
                    "messages": [*messages, self._repair_message(repair_hint)],
                    "options": self._options(temperature=0.0, num_predict=self._tool_num_predict),
                }
            data = await self._post_chat(attempt_payload, correlation_id)

            # Fix #1: an explicit decline ("no tool / clarify") is a valid terminal
            # no-tool decision — stop here instead of retrying it into a hallucinated
            # tool call.
            if self._enable_decline_retry and self._is_decline_response(data):
                self.last_tool_attempts.append({"attempt": attempt + 1, "valid": True, "declined": True})
                declined = True
                break

            try:
                candidate = self._extract_tool_call(data)
                if candidate is None:
                    raise LlmGatewayError("Ollama returned no tool call")
                if self._enable_argument_normalization:
                    candidate = self._normalize_arguments(candidate)
                self._tool_router.validate(candidate, check_ranges=self._enable_range_validation)
                tool_call = candidate
                self.last_tool_attempts.append({"attempt": attempt + 1, "valid": True})
                break
            except (LlmGatewayError, ToolValidationError) as exc:
                repair_hint = str(exc)
                no_tool = isinstance(exc, LlmGatewayError) and "no tool call" in str(exc)
                # Fix #1 (core): a clean no-tool first pass is the model *deliberately
                # declining*, not a malformed output to repair. Phase-2-A collapsed the
                # decline categories by retrying these (coercion); Phase-2-B's first cut
                # then collapsed them a second way by handing the clean decline to the
                # action-happy rule-based fallback. Both are wrong: honor the decline as
                # a terminal no-tool result. Only a *malformed or out-of-range* tool call
                # is worth repairing/falling back on.
                self.last_tool_attempts.append(
                    {
                        "attempt": attempt + 1,
                        "valid": bool(self._enable_decline_retry and no_tool),
                        "error": repair_hint,
                    }
                )
                if self._enable_decline_retry and no_tool:
                    declined = True
                    break
        if tool_call is not None:
            return tool_call
        if declined:
            # The model cleanly chose no tool — do not let the fallback re-act on it.
            return None
        # The LLM produced only malformed/out-of-range output. Here the rule-based
        # fallback earns its keep: it parses the user message and returns a tool only
        # for a clear intent, otherwise None. Fix #2: range-check its output too, so it
        # cannot smuggle back a value the validator just rejected.
        if self._enable_rule_based_fallback:
            fallback = build_rule_based_tool_call(user_message, station)
            if fallback is not None and self._enable_range_validation:
                try:
                    self._tool_router.validate(fallback, check_ranges=True)
                except ToolValidationError:
                    return None
            return fallback
        return None

    async def generate_report(
        self,
        event: DomainEvent,
        command: RobotCommand,
        correlation_id: str,
        evaluation: str | None = None,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": self._prompt_store.render("report_system"),
                },
                {
                    "role": "user",
                    "content": self._prompt_store.render(
                        "report_user",
                        event_context=self._compact_event_context(event),
                        command_context=self._compact_command_context(command),
                        evaluation_context=evaluation or "none",
                        knowledge_context=format_knowledge_block(knowledge),
                    ),
                },
            ],
            "options": self._options(temperature=0.2, num_predict=self._report_num_predict),
        }
        data = await self._post_chat(payload, correlation_id)
        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise LlmGatewayError("Ollama returned an empty report message")
        return content

    async def generate_chat_response(
        self,
        user_message: str,
        history: list[dict[str, str]],
        correlation_id: str,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str:
        system_content = (
            "당신은 AGV 공정 제어 가상 디지털 트윈 어시스턴트입니다. "
            "이전 대화 맥락을 참고해 자연스럽게 답변하세요. "
            "공정 제어 명령(시뮬레이션 시작/정지, 스테이션 작업 등)은 직접 실행하지 말고 "
            "사용자가 명확한 명령어를 입력하도록 안내하세요. 답변은 한국어로 간결하게 하세요."
        )
        knowledge_block = format_knowledge_block(knowledge)
        if knowledge_block != "none":
            system_content += (
                "\n\n아래 참고 문서를 우선 근거로 답변하고, 사용한 문서 제목을 인용하세요. "
                '문서에 없는 내용은 지어내지 말고 "not in the knowledge base"라고 답하세요.'
                "\n\n참고 문서:\n" + knowledge_block
            )
        else:
            system_content += (
                '\n\nIf the user asks for operational facts that require VCORE knowledge, answer '
                '"not in the knowledge base" instead of inventing details.'
            )
        messages = [
            {"role": "system", "content": system_content},
            *history[-8:],
            {"role": "user", "content": user_message},
        ]
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "messages": messages,
            "options": self._options(temperature=0.3, num_predict=256),
        }
        data = await self._post_chat(payload, correlation_id)
        content = (data.get("message", {}).get("content") or "").strip()
        if not content:
            raise LlmGatewayError("Empty chat response from Ollama")
        return content

    async def _post_chat(self, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                    headers={"x-correlation-id": correlation_id},
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError("Ollama request timed out") from exc
        except httpx.HTTPError as exc:
            raise LlmGatewayError(f"Ollama request failed: {exc}") from exc
        except ValueError as exc:
            raise LlmGatewayError("Ollama returned invalid JSON") from exc

    # Canonical "no tool is correct" sentinels the model may emit on a repair retry.
    _DECLINE_NAMES = {"none", "no_tool", "no-tool", "noop", "null", "clarify", "clarification"}
    _DECLINE_DECISIONS = {"none", "no_tool", "decline", "clarify", "clarification"}

    def _repair_message(self, repair_hint: str) -> dict[str, str]:
        """Build the repair-retry user turn.

        Fix #1: when decline is permitted the prompt is *non-coercive* — it offers an
        explicit no-tool escape hatch so a correct decline (ambiguous request, missing
        or out-of-range parameter, negative-control query) is no longer forced into a
        hallucinated tool call. With the flag off it keeps the Phase-2-A coercive text.
        """
        if self._enable_decline_retry:
            content = (
                "The previous response failed validation. "
                f"Validation error: {repair_hint}. "
                "If one tool clearly satisfies the request, return exactly one valid JSON "
                'object: {"name": <tool>, "arguments": {...}} with arguments matching the '
                "tool schema. If the request is ambiguous, is missing a required parameter, "
                "uses an out-of-range value, or is not an AGV/simulation control command, do "
                'NOT invent a tool — return exactly {"name": "none", "arguments": {}}.'
            )
        else:
            content = (
                "The previous response failed validation. Return exactly one valid "
                "JSON object with name and arguments matching the tool schema. "
                f"Validation error: {repair_hint}"
            )
        return {"role": "user", "content": content}

    def _is_decline_response(self, data: dict[str, Any]) -> bool:
        """Detect a no-actionable-tool / clarification decision in a raw chat response.

        Returns True for every way the model can say "no tool": a decline sentinel in a
        native tool call, empty content, or a JSON object that names a decline word or no
        usable tool at all (``{}``, ``{"arguments": {...}}``). Returns False only when the
        model named a real tool (let validation handle it) or emitted unparseable
        non-JSON prose (let the extract/repair path treat it as malformed).
        """
        message = data.get("message", {})
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            name = (tool_calls[0].get("function", {}) or {}).get("name")
            return isinstance(name, str) and name.strip().lower() in self._DECLINE_NAMES
        content = (message.get("content") or "").strip()
        if not content:
            return True
        try:
            parsed = self._parse_json_content(content)
        except LlmGatewayError:
            return False
        name = parsed.get("name") or parsed.get("tool") or parsed.get("tool_name")
        if isinstance(name, str) and name.strip().lower() in self._DECLINE_NAMES:
            return True
        decision = parsed.get("decision") or parsed.get("action")
        if isinstance(decision, str) and decision.strip().lower() in self._DECLINE_DECISIONS:
            return True
        if parsed.get("clarify") is True or parsed.get("clarification_needed") is True:
            return True
        # A JSON object that names no usable tool is a no-op decision, not a malformed
        # command to repair/coerce into action.
        return not (isinstance(name, str) and name.strip())

    def _extract_tool_call(self, data: dict[str, Any]) -> ToolCall | None:
        message = data.get("message", {})
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            function = tool_calls[0].get("function", {})
            return self._tool_call_from_parts(function.get("name"), function.get("arguments", {}))

        content = (message.get("content") or "").strip()
        if not content:
            return None
        try:
            parsed = self._parse_json_content(content)
        except LlmGatewayError:
            return None
        try:
            return ToolCallDecision.from_llm_payload(parsed)
        except ValueError as exc:
            raise LlmGatewayError("Ollama tool response failed schema validation") from exc

    def _extract_plan_steps(self, data: dict[str, Any]) -> list[str]:
        content = (data.get("message", {}).get("content") or "").strip()
        if not content:
            raise LlmGatewayError("Ollama returned an empty plan message")
        parsed = self._parse_json_content(content)
        try:
            return PlanDecision.model_validate(parsed).steps
        except Exception as exc:
            raise LlmGatewayError("Ollama plan response failed schema validation") from exc

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if match is None:
                raise LlmGatewayError("Ollama returned non-JSON content")
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise LlmGatewayError("Ollama returned invalid plan JSON") from exc
        if not isinstance(parsed, dict):
            raise LlmGatewayError("Ollama JSON response must be an object")
        return parsed

    def _tool_call_from_parts(self, name: str | None, arguments: Any) -> ToolCall | None:
        if name is None:
            return None
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise LlmGatewayError("Ollama tool arguments were not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise LlmGatewayError("Ollama tool arguments must be an object")
        try:
            command_name = RobotCommandName(name)
        except ValueError as exc:
            raise LlmGatewayError(f"Ollama returned unsupported tool: {name}") from exc
        return ToolCall(name=command_name, arguments=arguments)

    def _normalize_arguments(self, tool_call: ToolCall) -> ToolCall:
        """Optional Phase-2 normalization step: coerce stringified numbers into the
        types the schema expects (e.g. ``"3"`` -> ``3``) before validation. Measures
        how many otherwise-valid calls a cheap deterministic coercion rescues."""
        arguments = dict(tool_call.arguments)
        for key in ("station_id", "agv_count"):
            arguments[key] = _coerce_int(arguments[key]) if key in arguments else arguments.get(key)
            if key not in tool_call.arguments:
                arguments.pop(key, None)
        if "speed_multiplier" in arguments:
            arguments["speed_multiplier"] = _coerce_float(arguments["speed_multiplier"])
        return ToolCall(name=tool_call.name, arguments=arguments)

    def _compact_station_context(self, station: Station | None) -> str:
        if station is None:
            return "{}"
        return self._json_compact(
            {
                "station_id": station.station_id,
                "station_type": station.station_type,
                "task_ready": station.task_ready,
                "cell_id": station.cell_id,
                "zone": station.zone,
            }
        )

    def _compact_event_context(self, event: DomainEvent) -> str:
        payload = {
            key: value
            for key, value in event.payload.items()
            if key in {"robot_id", "reason", "status", "station_id", "progress", "kpis", "verdict"}
        }
        return self._json_compact(
            {
                "event_type": event.event_type,
                "session_id": event.session_id,
                "command_id": event.command_id,
                "payload": payload,
            }
        )

    def _compact_command_context(self, command: RobotCommand) -> str:
        return self._json_compact(
            {
                "command_id": command.command_id,
                "command_name": command.command_name.value,
                "status": command.status.value,
                "parameters": command.parameters,
            }
        )

    def _json_compact(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    def _options(self, temperature: float, num_predict: int) -> dict[str, Any]:
        return {
            "temperature": temperature,
            "num_ctx": self._num_ctx,
            "num_predict": num_predict,
        }


class LlamaCppLlmGateway(OllamaLlmGateway):
    """llama.cpp server gateway using the OpenAI-compatible chat completions API.

    The public behavior intentionally mirrors ``OllamaLlmGateway`` so the chatbot
    agents and benchmark harness can compare both providers through one boundary.
    """

    async def _post_chat(self, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        options = payload.get("options") or {}
        request: dict[str, Any] = {
            "model": payload.get("model") or self._model,
            "messages": payload.get("messages") or [],
            "stream": False,
            "temperature": options.get("temperature", 0.0),
        }
        if "num_predict" in options:
            request["max_tokens"] = options["num_predict"]
        if payload.get("format") == "json":
            request["response_format"] = {"type": "json_object"}
        if payload.get("tools"):
            request["tools"] = payload["tools"]
            request["tool_choice"] = "auto"
        if self._adapter_scale is not None:
            # Per-request LoRA scale: applied only to this slot, so a concurrent chat
            # request at scale 0.0 and a routing request at scale 1.0 don't interfere.
            request["lora"] = [{"id": 0, "scale": self._adapter_scale}]

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=request,
                    headers={"x-correlation-id": correlation_id},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError("llama.cpp request timed out") from exc
        except httpx.HTTPError as exc:
            raise LlmGatewayError(f"llama.cpp request failed: {exc}") from exc
        except ValueError as exc:
            raise LlmGatewayError("llama.cpp returned invalid JSON") from exc

        return self._normalize_openai_chat_response(data)

    def _normalize_openai_chat_response(self, data: dict[str, Any]) -> dict[str, Any]:
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        return {
            "message": {
                "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls") or [],
            }
        }


class PathActionRoutingGateway(LlamaCppLlmGateway):
    """Routing gateway for the integrated path/action SFT model.

    That model speaks a different protocol than the tool-planning gateway: under the
    ``path_action_system`` prompt it emits ``{"route","action","arguments"}`` (not
    ``{"name","arguments"}``). It is meant to run with the LoRA adapter applied
    (``adapter_scale=1.0``). Only a ``robot_command`` route with a user-facing action
    becomes a ``ToolCall``; every other route (status queries, optimize, clarify,
    no_action) and the internal-only ``move_to_station`` resolve to ``None`` so the
    orchestrator's own routing handles them.
    """

    async def propose_tool_call(
        self,
        user_message: str,
        station: Station | None,
        correlation_id: str,
    ) -> ToolCall | None:
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": self._prompt_store.render("path_action_system")},
                {"role": "user", "content": user_message},
            ],
            "format": "json",
            "options": self._options(temperature=0.0, num_predict=self._tool_num_predict),
        }
        self.last_tool_attempts = []
        data = await self._post_chat(payload, correlation_id)
        content = (data.get("message", {}).get("content") or "").strip()
        if not content:
            self.last_tool_attempts.append({"attempt": 1, "valid": True, "declined": True})
            return None
        try:
            parsed = self._parse_json_content(content)
        except LlmGatewayError:
            self.last_tool_attempts.append({"attempt": 1, "error": "non-JSON output"})
            return None

        route = parsed.get("route")
        action = parsed.get("action")
        if route != "robot_command" or not action:
            self.last_tool_attempts.append(
                {"attempt": 1, "valid": True, "declined": True, "route": route}
            )
            return None
        try:
            candidate = ToolCall(
                name=RobotCommandName(action),
                arguments=parsed.get("arguments") or {},
            )
        except ValueError:
            self.last_tool_attempts.append({"attempt": 1, "error": f"unknown action: {action}"})
            return None
        # move_to_station is internal-only (mirrors build_rule_based_tool_call): a user
        # request never maps to it, so let the ambiguous-command path handle it.
        if candidate.name == RobotCommandName.MOVE_TO_STATION:
            self.last_tool_attempts.append({"attempt": 1, "valid": True, "declined": True})
            return None
        if self._enable_argument_normalization:
            candidate = self._normalize_arguments(candidate)
        try:
            self._tool_router.validate(candidate, check_ranges=self._enable_range_validation)
        except ToolValidationError as exc:
            self.last_tool_attempts.append({"attempt": 1, "error": str(exc)})
            return None
        self.last_tool_attempts.append({"attempt": 1, "valid": True})
        return candidate


class RoutingSplitLlmGateway:
    """Routes tool-call planning to a dedicated (SFT) gateway, everything else to a general one.

    Phase 3 fine-tuned only ``propose_tool_call`` (tool routing). Conversational tasks
    (intent classification, plan narration, chat, reports) were not trained, so they stay
    on the general gateway. This keeps the SFT model on the task it was tuned for while
    preserving free-form quality elsewhere.
    """

    def __init__(self, general: Any, routing: Any) -> None:
        self._general = general
        self._routing = routing

    @property
    def last_tool_attempts(self) -> list[dict[str, Any]]:
        return getattr(self._routing, "last_tool_attempts", [])

    async def preload(self, correlation_id: str = "startup-preload") -> None:
        for gateway in (self._general, self._routing):
            preload = getattr(gateway, "preload", None)
            if preload is not None:
                await preload(correlation_id)

    async def classify_intent(self, user_message: str, correlation_id: str) -> str | None:
        return await self._general.classify_intent(user_message, correlation_id)

    async def generate_plan_steps(self, user_message: str, correlation_id: str) -> list[str]:
        return await self._general.generate_plan_steps(user_message, correlation_id)

    async def propose_tool_call(
        self,
        user_message: str,
        station: Station | None,
        correlation_id: str,
    ) -> ToolCall | None:
        return await self._routing.propose_tool_call(user_message, station, correlation_id)

    async def generate_report(
        self,
        event: DomainEvent,
        command: RobotCommand,
        correlation_id: str,
        evaluation: str | None = None,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str:
        return await self._general.generate_report(
            event, command, correlation_id, evaluation, knowledge
        )

    async def generate_chat_response(
        self,
        user_message: str,
        history: list[dict[str, str]],
        correlation_id: str,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str:
        return await self._general.generate_chat_response(
            user_message, history, correlation_id, knowledge
        )


class RuleBasedLlmGateway:
    """Deterministic demo gateway that keeps the LLM boundary mockable."""

    async def preload(self, correlation_id: str = "startup-preload") -> None:
        return None

    async def classify_intent(
        self,
        user_message: str,
        correlation_id: str,
    ) -> str | None:
        # No LLM available: defer to the orchestrator's keyword-based routing fallback.
        return None

    async def generate_plan_steps(
        self,
        user_message: str,
        correlation_id: str,
    ) -> list[str]:
        return RuleBasedPlanningFallback().build_steps(user_message)

    async def propose_tool_call(
        self,
        user_message: str,
        station: Station | None,
        correlation_id: str,
    ) -> ToolCall | None:
        return build_rule_based_tool_call(user_message, station)

    async def generate_chat_response(
        self,
        user_message: str,
        history: list[dict[str, str]],
        correlation_id: str,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str:
        return (
            "저는 AGV 공정 제어 어시스턴트입니다. "
            "시뮬레이션 시작/정지, 공정 상태 조회, 스테이션 작업 지시 등을 도와드릴 수 있습니다. "
            "무엇을 도와드릴까요?"
        )

    async def generate_report(
        self,
        event: DomainEvent,
        command: RobotCommand,
        correlation_id: str,
        evaluation: str | None = None,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str:
        station_id = command.parameters.get("station_id")
        if event.event_type == "robot.command.completed":
            if command.command_name == RobotCommandName.RUN_STATION_TASK:
                base = f"{station_id}번 스테이션 작업이 완료되었습니다."
            elif command.command_name == RobotCommandName.START_SIMULATION:
                base = "가상 공정 시뮬레이션을 시작했습니다."
            elif command.command_name == RobotCommandName.STOP_SIMULATION:
                base = "가상 공정 시뮬레이션을 정지했습니다."
            else:
                base = f"{station_id}번 스테이션 작업이 완료되었습니다."
            return f"{base}\n\n{evaluation}" if evaluation else base
        reason = event.payload.get("reason", "원인을 확인할 수 없습니다.")
        return f"{station_id}번 스테이션 작업이 실패했습니다. 원인: {reason}"



def build_rule_based_tool_call(user_message: str, station: Station | None) -> ToolCall | None:
    normalized = user_message.lower()

    if _contains_any(normalized, ("pause", "hold", "일시정지", "일시 정지", "멈춰", "잠깐")):
        return ToolCall(name=RobotCommandName.PAUSE_SIMULATION, arguments={})
    if _contains_any(normalized, ("resume", "continue", "재개", "다시 시작", "계속")):
        return ToolCall(name=RobotCommandName.RESUME_SIMULATION, arguments={})
    if _contains_any(normalized, ("speed", "속도", "배속", "빠르게", "느리게")):
        multiplier = _extract_speed_multiplier(user_message)
        if multiplier is not None:
            return ToolCall(
                name=RobotCommandName.SET_SIM_SPEED,
                arguments={"speed_multiplier": multiplier},
            )
    if _contains_any(
        normalized,
        (
            "start sim",
            "start simulation",
            "run simulation",
            "run sim",
            "launch",
            "deploy",
            "시뮬레이션 시작",
            "시작해",
            "실행",
            "돌려",
            "돌리",
            "돌린",
            "돌립",
            "가동",
            "배치",
            "투입",
        ),
    ):
        arguments: dict[str, Any] = {}
        agv_count = _extract_agv_count(user_message)
        if agv_count is not None:
            arguments["agv_count"] = agv_count
        multiplier = _extract_speed_multiplier(user_message)
        if multiplier is not None:
            arguments["speed_multiplier"] = multiplier
        acceptance = _extract_acceptance(user_message)
        if acceptance:
            arguments["acceptance"] = acceptance
        return ToolCall(name=RobotCommandName.START_SIMULATION, arguments=arguments)
    if _contains_any(
        normalized,
        (
            "stop sim", "stop simulation", "abort", "emergency stop",
            "시뮬레이션 정지", "정지", "중단", "종료", "끝내",
        ),
    ):
        return ToolCall(name=RobotCommandName.STOP_SIMULATION, arguments={})

    station_id = station.station_id if station else extract_station_id(user_message)
    if station_id is None:
        agv_count = _extract_agv_count(user_message)
        if agv_count is not None and (
            _contains_any(normalized, ("add agv", "agv 추가", "agv 더", "추가", "add"))
            or ("agv" in normalized and _contains_any(normalized, ("add", "추가", "더", "+")))
        ):
            return ToolCall(
                name=RobotCommandName.START_SIMULATION,
                arguments={"agv_count": agv_count},
            )
        return None
    if _contains_any(normalized, ("run", "task", "작업", "수행", "처리")):
        return ToolCall(
            name=RobotCommandName.RUN_STATION_TASK,
            arguments={"station_id": station_id},
        )
    # move_to_station is internal-only: a user "move/보내" request no longer maps to a tool
    # (returns None → ambiguous-command path). The contract stays for internal/agent-plan use.
    if _contains_any(normalized, ("inspect", "check", "검사", "확인", "상태")):
        return ToolCall(
            name=RobotCommandName.INSPECT_STATION,
            arguments={"station_id": station_id},
        )
    return None


def _coerce_int(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"-?\d+\.0+", stripped):
            return int(float(stripped))
    return value


def _coerce_float(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip().rstrip("xX배")
        try:
            return float(stripped)
        except ValueError:
            return value
    return value


def extract_station_id(text: str) -> int | None:
    patterns = (
        r"(?:station|스테이션|구역)\s*#?\s*(\d+)",
        r"(\d+)\s*(?:번)?\s*(?:station|스테이션|구역)",
        r"station\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_speed_multiplier(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|배|배속)", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"(?:speed|속도)\s*(?:to|=|:|를|을)?\s*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _extract_agv_count(text: str) -> int | None:
    patterns = (
        r"agv\s*(\d+)\s*(?:대|개)?",
        r"(\d+)\s*(?:대|개)?\s*agv",
        r"(\d+)\s*(?:대|개)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_acceptance(text: str) -> list[dict[str, Any]]:
    """Parse verifiable KPI goals from a natural-language sim request into F4 acceptance
    criteria, so the deterministic path still yields a PASS/FAIL verdict when the LLM is
    unavailable. Matches phrasings like '처리량 시간당 70 이상', '평균 대기 12초 이하', '충돌 0건'."""
    checks: list[dict[str, Any]] = []

    throughput = re.search(
        r"처리량\D*?(\d+(?:\.\d+)?)\s*(?:이상|초과|넘|>=)", text
    ) or re.search(r"throughput\D*?(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if throughput:
        value = float(throughput.group(1))
        checks.append(
            {
                "metric": "throughput",
                "comparator": ">=",
                "threshold": value,
                "label": f"throughput >= {throughput.group(1)}/h",
            }
        )

    wait = re.search(
        r"(?:평균\s*대기|대기\s*시간|avg\s*wait)\D*?(\d+(?:\.\d+)?)\s*(?:초|s|sec)?\s*(?:이하|미만|이내|<=)",
        text,
        flags=re.IGNORECASE,
    )
    if wait:
        checks.append(
            {
                "metric": "avg_wait_sec",
                "comparator": "<=",
                "threshold": float(wait.group(1)),
                "label": f"avg_wait <= {wait.group(1)}s",
            }
        )

    if re.search(r"충돌\s*(?:0|영|없|제로|zero)", text) or re.search(
        r"(?:collision|crash)\w*\s*(?:0|zero|none)", text, flags=re.IGNORECASE
    ):
        checks.append(
            {
                "metric": "collision_count",
                "comparator": "==",
                "threshold": 0.0,
                "label": "collisions == 0",
            }
        )
    else:
        collisions = re.search(r"충돌\D*?(\d+)\s*건?\s*(?:이하|미만|<=)", text)
        if collisions:
            checks.append(
                {
                    "metric": "collision_count",
                    "comparator": "<=",
                    "threshold": float(collisions.group(1)),
                    "label": f"collisions <= {collisions.group(1)}",
                }
            )

    return checks


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


async def _clean_rule_based_generate_report(
    self: RuleBasedLlmGateway,
    event: DomainEvent,
    command: RobotCommand,
    correlation_id: str,
    evaluation: str | None = None,
    knowledge: list[RetrievedChunk] | None = None,
) -> str:
    station_id = command.parameters.get("station_id")
    if event.event_type == "robot.command.completed":
        verdict_line = format_verdict_summary(event.payload.get("verdict"))
        if command.command_name == RobotCommandName.RUN_STATION_TASK:
            base = f"Station {station_id} task is complete."
        elif command.command_name == RobotCommandName.MOVE_TO_STATION:
            base = f"AGV moved to Station {station_id}."
        elif command.command_name == RobotCommandName.START_SIMULATION:
            base = "Simulation started."
        elif command.command_name == RobotCommandName.STOP_SIMULATION:
            base = "Simulation stopped."
        elif command.command_name == RobotCommandName.PAUSE_SIMULATION:
            base = "Simulation paused."
        elif command.command_name == RobotCommandName.RESUME_SIMULATION:
            base = "Simulation resumed."
        elif command.command_name == RobotCommandName.SET_SIM_SPEED:
            base = f"Simulation speed set to {command.parameters.get('speed_multiplier')}x."
        else:
            base = "Command completed."
        report = f"{base} {verdict_line}" if verdict_line else base
        return f"{report}\n\n{evaluation}" if evaluation else report
    return f"Command failed. Reason: {event.payload.get('reason', 'unknown')}"


RuleBasedLlmGateway.generate_report = _clean_rule_based_generate_report
