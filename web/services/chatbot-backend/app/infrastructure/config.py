from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "chatbot-backend"
    environment: str = "development"
    control_server_base_url: str = "http://control-server-demo:8010"
    control_server_client_mode: str = "mock"
    # UE5 Virtual Process (AGVSimController HTTP server, default :7777 on the host)
    ue5_base_url: str = "http://host.docker.internal:7777"
    ue5_client_mode: str = "mock"
    ue5_view_url: str = "http://localhost:8880"
    # telemetry-collector HTTP ingest (in-Docker; UE5 telemetry arrives over the
    # backend WebSocket and is forwarded here to bypass the Windows Docker proxy).
    telemetry_collector_url: str = "http://telemetry-collector:8030"
    agv_api_key: str = "dev-agv-key"
    # Fallback cell fleet size used only when UE5 /sim/status does not report max_agvs
    # (e.g. mock mode or UE5 unreachable). The live value is read from UE5 at request time.
    agv_fleet_max: int = 5
    database_url: str | None = None
    session_repository: str = "memory"
    # "ollama" | "llama_cpp" | "routing_split" | "rule_based". routing_split serves the
    # SFT tool-router on llama.cpp for propose_tool_call and keeps Ollama for chat/plan/report.
    llm_provider: str = "ollama"
    routing_split_tool_template: str = "tool_planning_system_min"
    # adapter_toggle provider: per-request LoRA scale applied to the single llama.cpp base.
    # 1.0 = SFT routing adapter (propose_tool_call); 0.0 = bare base (chat/report/plan).
    adapter_routing_scale: float = 1.0
    adapter_general_scale: float = 0.0
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3.5:0.8b"
    ollama_timeout_seconds: float = 120.0
    ollama_num_ctx: int = 2048
    ollama_plan_num_predict: int = 192
    ollama_tool_num_predict: int = 128
    ollama_report_num_predict: int = 512
    llama_cpp_base_url: str = "http://localhost:8080"
    llama_cpp_model: str = "local-llama-cpp"
    llama_cpp_timeout_seconds: float = 120.0
    llama_cpp_num_ctx: int = 2048
    llama_cpp_plan_num_predict: int = 192
    llama_cpp_tool_num_predict: int = 128
    llama_cpp_report_num_predict: int = 512
    llm_structured_retry_count: int = 1
    # RAG / knowledge retrieval (spec_rag.md §5.5). Off by default so the demo runs without Qdrant.
    rag_enabled: bool = False
    qdrant_url: str = "http://qdrant:6333"
    rag_collection: str = "vcore_operations_ko"
    rag_embed_model: str = "bge-m3"
    rag_top_k: int = 5
    rag_fetch_k: int = 10
    rag_rerank_mode: str = "lexical"
    rag_min_score: float = 0.0
    rag_rerank_base_url: str | None = None
    rag_rerank_model: str | None = None
    graph_rag_enabled: bool = True
    # Embeddings run on Ollama's /v1/embeddings (engine split: LLM on llama.cpp, embeddings on
    # Ollama). Independent of the LLM base URL so they can be served by different engines.
    embed_base_url: str = "http://ollama:11434"
    session_history_limit: int = 40
    session_history_message_max_chars: int = 1200
    session_preview_max_chars: int = 80
    robot_command_timeout_seconds: int = 30
    robot_command_retry_count: int = 2
    auto_complete_demo_commands: bool = True
    correlation_id_header: str = "x-correlation-id"
    cors_allow_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5180",
        "http://127.0.0.1:5180",
        "http://localhost:5199",
        "http://127.0.0.1:5199",
    )


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "chatbot-backend"),
        environment=os.getenv("ENVIRONMENT", "development"),
        control_server_base_url=os.getenv(
            "CONTROL_SERVER_BASE_URL", "http://control-server-demo:8010"
        ),
        control_server_client_mode=os.getenv("CONTROL_SERVER_CLIENT_MODE", "mock"),
        ue5_base_url=os.getenv("UE5_BASE_URL", "http://host.docker.internal:7777"),
        ue5_client_mode=os.getenv("UE5_CLIENT_MODE", "mock"),
        ue5_view_url=os.getenv("UE5_VIEW_URL", "http://localhost:8880"),
        telemetry_collector_url=os.getenv(
            "TELEMETRY_COLLECTOR_URL", "http://telemetry-collector:8030"
        ),
        agv_api_key=os.getenv("AGV_API_KEY", "dev-agv-key"),
        agv_fleet_max=int(os.getenv("AGV_FLEET_MAX", "5")),
        database_url=os.getenv("DATABASE_URL"),
        session_repository=os.getenv(
            "SESSION_REPOSITORY",
            "postgres" if os.getenv("DATABASE_URL") else "memory",
        ),
        llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
        routing_split_tool_template=os.getenv(
            "ROUTING_SPLIT_TOOL_TEMPLATE", "tool_planning_system_min"
        ),
        adapter_routing_scale=float(os.getenv("ADAPTER_ROUTING_SCALE", "1.0")),
        adapter_general_scale=float(os.getenv("ADAPTER_GENERAL_SCALE", "0.0")),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:0.8b"),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
        ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "2048")),
        ollama_plan_num_predict=int(os.getenv("OLLAMA_PLAN_NUM_PREDICT", "192")),
        ollama_tool_num_predict=int(os.getenv("OLLAMA_TOOL_NUM_PREDICT", "128")),
        ollama_report_num_predict=int(os.getenv("OLLAMA_REPORT_NUM_PREDICT", "512")),
        llama_cpp_base_url=os.getenv("LLAMA_CPP_BASE_URL", "http://localhost:8080"),
        llama_cpp_model=os.getenv("LLAMA_CPP_MODEL", "local-llama-cpp"),
        llama_cpp_timeout_seconds=float(os.getenv("LLAMA_CPP_TIMEOUT_SECONDS", "120")),
        llama_cpp_num_ctx=int(os.getenv("LLAMA_CPP_NUM_CTX", "2048")),
        llama_cpp_plan_num_predict=int(os.getenv("LLAMA_CPP_PLAN_NUM_PREDICT", "192")),
        llama_cpp_tool_num_predict=int(os.getenv("LLAMA_CPP_TOOL_NUM_PREDICT", "128")),
        llama_cpp_report_num_predict=int(os.getenv("LLAMA_CPP_REPORT_NUM_PREDICT", "512")),
        llm_structured_retry_count=int(os.getenv("LLM_STRUCTURED_RETRY_COUNT", "1")),
        rag_enabled=os.getenv("RAG_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        rag_collection=os.getenv("RAG_COLLECTION", "vcore_operations_ko"),
        rag_embed_model=os.getenv("RAG_EMBED_MODEL", "bge-m3"),
        rag_top_k=int(os.getenv("RAG_TOP_K", "5")),
        rag_fetch_k=int(os.getenv("RAG_FETCH_K", "10")),
        rag_rerank_mode=os.getenv("RAG_RERANK_MODE", "lexical"),
        rag_min_score=float(os.getenv("RAG_MIN_SCORE", "0.0")),
        rag_rerank_base_url=os.getenv("RAG_RERANK_BASE_URL"),
        rag_rerank_model=os.getenv("RAG_RERANK_MODEL"),
        graph_rag_enabled=os.getenv("GRAPH_RAG_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
        embed_base_url=os.getenv(
            "EMBED_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
        ),
        session_history_limit=int(os.getenv("SESSION_HISTORY_LIMIT", "40")),
        session_history_message_max_chars=int(
            os.getenv("SESSION_HISTORY_MESSAGE_MAX_CHARS", "1200")
        ),
        session_preview_max_chars=int(os.getenv("SESSION_PREVIEW_MAX_CHARS", "80")),
        robot_command_timeout_seconds=int(os.getenv("ROBOT_COMMAND_TIMEOUT_SECONDS", "30")),
        robot_command_retry_count=int(os.getenv("ROBOT_COMMAND_RETRY_COUNT", "2")),
        auto_complete_demo_commands=os.getenv("AUTO_COMPLETE_DEMO_COMMANDS", "true").lower()
        in {"1", "true", "yes", "on"},
        correlation_id_header=os.getenv("DEFAULT_CORRELATION_ID_HEADER", "x-correlation-id"),
        cors_allow_origins=tuple(
            origin.strip()
            for origin in os.getenv(
                "CORS_ALLOW_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5180,http://127.0.0.1:5180,http://localhost:5199,http://127.0.0.1:5199",
            ).split(",")
            if origin.strip()
        ),
    )
