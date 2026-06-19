from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.application.chat_orchestrator import ChatOrchestrator
from app.application.live_telemetry import LiveTelemetryHub
from app.application.robot_orchestrator import RobotCommandOrchestrator
from app.application.session_service import SessionService
from app.infrastructure.config import Settings, load_settings
from app.infrastructure.control_client import DemoControlServerClient, HttpControlServerClient
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.iot_client import DemoIotCommandClient
from app.infrastructure.knowledge_gateway import NullKnowledgeGateway, QdrantKnowledgeGateway
from app.infrastructure.llm_gateway import (
    LlamaCppLlmGateway,
    OllamaLlmGateway,
    PathActionRoutingGateway,
    RoutingSplitLlmGateway,
    RuleBasedLlmGateway,
)
from app.infrastructure.repositories import InMemorySessionRepository, PostgresSessionRepository
from app.infrastructure.ue5_client import Ue5CommandClient
from app.tools.router import ToolRouter

# Providers that load a local LLM (vs the always-ready rule-based gateway).
_LOCAL_LLM_PROVIDERS = {
    "ollama",
    "llama_cpp",
    "routing_split",
    "routing",
    "sft_routing",
    "adapter_toggle",
    "adapter",
    "lora_toggle",
}


class AppContainer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.repository = self._build_repository()
        self.events = InMemoryEventBus()
        self.live_telemetry = LiveTelemetryHub()
        self.control_client = self._build_control_client()
        self.iot_client = self._build_command_client()
        self.tool_router = ToolRouter()
        self.knowledge = self._build_knowledge_gateway()
        self.llm = self._build_llm_gateway()
        llm_provider = self.settings.llm_provider.lower()
        self.llm_status: dict[str, Any] = {
            "status": "loading" if llm_provider in _LOCAL_LLM_PROVIDERS else "ready",
            "provider": self.settings.llm_provider,
            "model": self._llm_model_name(),
            "message": "Loading local LLM model." if llm_provider in _LOCAL_LLM_PROVIDERS else "Rule-based gateway is ready.",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.sessions = SessionService(self.repository)
        self.robot_commands = RobotCommandOrchestrator(
            repository=self.repository,
            iot_client=self.iot_client,
            events=self.events,
        )
        self.chat = ChatOrchestrator(
            repository=self.repository,
            control_client=self.control_client,
            iot_telemetry=self.iot_client,
            llm=self.llm,
            robot_commands=self.robot_commands,
            events=self.events,
            tool_router=self.tool_router,
            live_telemetry=self.live_telemetry,
            knowledge=self.knowledge,
            rag_top_k=self.settings.rag_top_k,
            auto_complete_commands=(
                self.settings.auto_complete_demo_commands
                and not self._ue5_enabled()
            ),
            agv_fleet_max=self.settings.agv_fleet_max,
        )

    def set_llm_status(self, status: str, message: str) -> None:
        self.llm_status = {
            **self.llm_status,
            "status": status,
            "message": message,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def is_llm_ready(self) -> bool:
        return self.llm_status.get("status") == "ready"

    def _ue5_enabled(self) -> bool:
        return self.settings.ue5_client_mode.lower() in {"ue5", "http"}

    def _build_repository(self) -> InMemorySessionRepository | PostgresSessionRepository:
        if self.settings.session_repository.lower() == "postgres":
            if not self.settings.database_url:
                raise RuntimeError("SESSION_REPOSITORY=postgres requires DATABASE_URL.")
            return PostgresSessionRepository(self.settings.database_url)
        return InMemorySessionRepository()

    def _build_llm_gateway(
        self,
    ) -> RuleBasedLlmGateway | OllamaLlmGateway | LlamaCppLlmGateway | RoutingSplitLlmGateway:
        provider = self.settings.llm_provider.lower()
        if provider == "ollama":
            return self._build_ollama_gateway()
        if provider in {"llama_cpp", "llamacpp", "llama.cpp"}:
            return self._build_llama_cpp_gateway()
        if provider in {"routing_split", "routing", "sft_routing"}:
            # SFT tool-router (llama.cpp) for propose_tool_call; Ollama for everything else.
            # The routing gateway is prompted exactly as the SFT model was trained: minimal
            # system prompt, bare user command, no tool schema, decline-retry on so the
            # model's clarify/none outputs resolve to a clean no-tool decision.
            routing = self._build_llama_cpp_gateway(
                tool_system_template=self.settings.routing_split_tool_template,
                tool_user_template=None,
                send_tool_schema=False,
                enable_decline_retry=True,
                enable_range_validation=True,
                enable_argument_normalization=True,
            )
            return RoutingSplitLlmGateway(general=self._build_ollama_gateway(), routing=routing)
        if provider in {"adapter_toggle", "adapter", "lora_toggle"}:
            # Single base model + routing LoRA on ONE llama.cpp endpoint. propose_tool_call
            # runs with the adapter applied (scale 1.0 = SFT router); chat/report/plan/intent
            # run on the bare base (scale 0.0). Collapses routing_split's two models into one
            # in-VRAM base + a ~22MB adapter. llama.cpp must be launched with --lora <adapter>
            # --lora-init-without-apply so per-request scale controls application.
            routing = self._build_llama_cpp_gateway(
                gateway_cls=PathActionRoutingGateway,
                adapter_scale=self.settings.adapter_routing_scale,
                enable_range_validation=True,
                enable_argument_normalization=True,
            )
            general = self._build_llama_cpp_gateway(
                adapter_scale=self.settings.adapter_general_scale,
            )
            return RoutingSplitLlmGateway(general=general, routing=routing)
        return RuleBasedLlmGateway()

    def _build_knowledge_gateway(self) -> NullKnowledgeGateway | QdrantKnowledgeGateway:
        if not self.settings.rag_enabled:
            return NullKnowledgeGateway()
        return QdrantKnowledgeGateway(
            qdrant_url=self.settings.qdrant_url,
            collection=self.settings.rag_collection,
            embed_base_url=self.settings.embed_base_url,
            embed_model=self.settings.rag_embed_model,
        )

    def _build_ollama_gateway(self) -> OllamaLlmGateway:
        return OllamaLlmGateway(
            base_url=self.settings.ollama_base_url,
            model=self.settings.ollama_model,
            timeout_seconds=self.settings.ollama_timeout_seconds,
            num_ctx=self.settings.ollama_num_ctx,
            plan_num_predict=self.settings.ollama_plan_num_predict,
            tool_num_predict=self.settings.ollama_tool_num_predict,
            report_num_predict=self.settings.ollama_report_num_predict,
            structured_retry_count=self.settings.llm_structured_retry_count,
            tool_router=self.tool_router,
        )

    def _build_llama_cpp_gateway(
        self, gateway_cls: type[LlamaCppLlmGateway] = LlamaCppLlmGateway, **overrides: Any
    ) -> LlamaCppLlmGateway:
        return gateway_cls(
            base_url=self.settings.llama_cpp_base_url,
            model=self.settings.llama_cpp_model,
            timeout_seconds=self.settings.llama_cpp_timeout_seconds,
            num_ctx=self.settings.llama_cpp_num_ctx,
            plan_num_predict=self.settings.llama_cpp_plan_num_predict,
            tool_num_predict=self.settings.llama_cpp_tool_num_predict,
            report_num_predict=self.settings.llama_cpp_report_num_predict,
            structured_retry_count=self.settings.llm_structured_retry_count,
            tool_router=self.tool_router,
            **overrides,
        )

    def _llm_model_name(self) -> str:
        provider = self.settings.llm_provider.lower()
        if provider == "ollama":
            return self.settings.ollama_model
        if provider in {"llama_cpp", "llamacpp", "llama.cpp"}:
            return self.settings.llama_cpp_model
        if provider in {"routing_split", "routing", "sft_routing"}:
            return f"{self.settings.llama_cpp_model} (routing) + {self.settings.ollama_model} (general)"
        if provider in {"adapter_toggle", "adapter", "lora_toggle"}:
            return f"{self.settings.llama_cpp_model} base + routing LoRA (adapter toggle)"
        return "rule_based"

    def _build_control_client(self) -> DemoControlServerClient | HttpControlServerClient:
        if self.settings.control_server_client_mode.lower() == "http":
            return HttpControlServerClient(base_url=self.settings.control_server_base_url)
        return DemoControlServerClient()

    def _build_command_client(self) -> DemoIotCommandClient | Ue5CommandClient:
        if self._ue5_enabled():
            return Ue5CommandClient(
                base_url=self.settings.ue5_base_url,
                api_key=self.settings.agv_api_key,
            )
        return DemoIotCommandClient()
