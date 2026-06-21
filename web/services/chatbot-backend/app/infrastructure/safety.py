from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import DomainEvent, RetrievedChunk


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SCRIPT_RE = re.compile(r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?82[-.\s]?)?0?1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")
_KOREAN_RRN_RE = re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b")
_SECRET_RE = re.compile(
    r"\b(?:bearer\s+)?(?:sk-[A-Za-z0-9_-]{16,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})\b",
    re.IGNORECASE,
)
_INJECTION_RE = re.compile(
    r"(?i)\b("
    r"ignore (?:all )?(?:previous|prior) instructions|"
    r"system prompt|developer message|"
    r"reveal (?:the )?(?:prompt|secret|api key)|"
    r"act as|jailbreak|do anything now"
    r")\b"
)
_DOMAIN_RE = re.compile(
    r"(?i)\b("
    r"agv|simulation|sim|station|zone|throughput|bottleneck|collision|kpi|ue5|unreal|"
    r"robot|fleet|cell|qdrant|rag|graph|ontology|vcore|process"
    r")\b"
)
_OUT_OF_SCOPE_RE = re.compile(
    r"(?i)\b("
    r"stock|weather|hotel|flight|restaurant|medical|legal|lawsuit|recipe|dating|"
    r"write a poem|essay about|movie recommendation"
    r")\b"
)


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    text: str
    reason: str | None = None
    redactions: dict[str, int] = field(default_factory=dict)


class SafetyGateway:
    refusal_message = (
        "I can help with VCORE AGV simulation, station operations, KPI analysis, "
        "RAG/GraphRAG knowledge, and related platform diagnostics. That request is outside "
        "this assistant's operational scope."
    )

    def sanitize_user_input(self, text: str) -> SafetyDecision:
        sanitized, redactions = self._sanitize_text(text)
        if self._is_prompt_attack(sanitized):
            return SafetyDecision(False, sanitized, "prompt_injection", redactions)
        if self._is_out_of_scope(sanitized):
            return SafetyDecision(False, sanitized, "out_of_scope", redactions)
        return SafetyDecision(True, sanitized, redactions=redactions)

    def sanitize_output(self, text: str) -> str:
        sanitized, _ = self._sanitize_text(text)
        return sanitized

    def sanitize_chunks(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        safe_chunks: list[RetrievedChunk] = []
        for chunk in chunks:
            title, _ = self._sanitize_text(chunk.title)
            source, _ = self._sanitize_text(chunk.source)
            text, _ = self._sanitize_text(chunk.text)
            text = _INJECTION_RE.sub("[retrieved-instruction-redacted]", text)
            safe_chunks.append(chunk.model_copy(update={"title": title, "source": source, "text": text}))
        return safe_chunks

    def redact_payload(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_pii(value)[0]
        if isinstance(value, list):
            return [self.redact_payload(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_payload(item) for item in value)
        if isinstance(value, dict):
            return {str(key): self.redact_payload(item) for key, item in value.items()}
        return value

    def redact_event(self, event: DomainEvent) -> DomainEvent:
        return event.model_copy(update={"payload": self.redact_payload(event.payload)})

    def _sanitize_text(self, text: str) -> tuple[str, dict[str, int]]:
        value = _CONTROL_CHARS_RE.sub("", text)
        value = _SCRIPT_RE.sub("", value)
        value = _TAG_RE.sub("", value)
        value = re.sub(r"\s+", " ", value).strip()
        return self._redact_pii(value)

    def _redact_pii(self, text: str) -> tuple[str, dict[str, int]]:
        redactions: dict[str, int] = {}

        def replace(pattern: re.Pattern[str], label: str, value: str) -> str:
            updated, count = pattern.subn(f"[redacted-{label}]", value)
            if count:
                redactions[label] = redactions.get(label, 0) + count
            return updated

        text = replace(_EMAIL_RE, "email", text)
        text = replace(_PHONE_RE, "phone", text)
        text = replace(_KOREAN_RRN_RE, "rrn", text)
        text = replace(_SECRET_RE, "secret", text)
        return text, redactions

    def _is_prompt_attack(self, text: str) -> bool:
        return bool(_INJECTION_RE.search(text))

    def _is_out_of_scope(self, text: str) -> bool:
        return bool(_OUT_OF_SCOPE_RE.search(text)) and not _DOMAIN_RE.search(text)


class TurnTraceSink:
    def __init__(self, safety: SafetyGateway) -> None:
        self._safety = safety

    def start(self) -> float:
        return time.perf_counter()

    async def publish(
        self,
        publisher: Any,
        *,
        session_id: str,
        correlation_id: str,
        trace: list[dict[str, Any]],
        user_text: str,
        assistant_text: str,
        started_at: float,
    ) -> DomainEvent:
        route = next(
            (
                item.get("route")
                for item in trace
                if item.get("node") == "classify_request" and item.get("route")
            ),
            None,
        )
        retrieval_hits = sum(
            int(item.get("hits") or 0)
            for item in trace
            if item.get("node") == "retrieve"
        )
        buckets: list[str] = []
        if route == "general_chat" and retrieval_hits == 0:
            buckets.append("low_grounding")
        if route == "robot_command" and not any(item.get("node") == "finalize_robot_command" for item in trace):
            buckets.append("possible_misroute")

        payload = {
            "trace_provider": "local_otel_shape",
            "span_name": "LangGraphMultiResponseAgent.handle",
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "route": route,
            "nodes": [item.get("node") for item in trace if item.get("node")],
            "retrieval_hits": retrieval_hits,
            "input_tokens_est": _token_estimate(user_text),
            "output_tokens_est": _token_estimate(assistant_text),
            "quality_buckets": buckets,
        }
        event = DomainEvent(
            event_type="agent.turn.traced",
            correlation_id=correlation_id,
            session_id=session_id,
            payload=self._safety.redact_payload(payload),
        )
        await publisher.publish(event)
        return event


def _token_estimate(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / 4))
