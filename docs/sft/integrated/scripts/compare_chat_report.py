"""Compare the integrated path/action SFT model vs the standard qwen3.5:2b on the
two tasks it was NOT trained for: report generation and general chat.

Runs the *actual backend code path* — OllamaLlmGateway / LlamaCppLlmGateway with the
real report_system / report_user templates and the in-code chat system prompt — against
both models, so the only variable is the model behind the gateway.

  - Standard : OllamaLlmGateway -> Ollama qwen3.5:2b   (http://localhost:11434)
  - SFT      : LlamaCppLlmGateway -> path/action GGUF  (http://localhost:8090)

Usage (from web/services/chatbot-backend):
  C:/Users/PC/anaconda3/python.exe ../../../docs/sft/integrated/scripts/compare_chat_report.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.agents.failure_policy import LlmGatewayError  # noqa: E402
from app.domain.models import (  # noqa: E402
    CommandStatus,
    DomainEvent,
    RobotCommand,
    RobotCommandName,
)
from app.infrastructure.llm_gateway import LlamaCppLlmGateway, OllamaLlmGateway  # noqa: E402

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3.5:2b"
SFT_URL = "http://localhost:8090"


def _cmd(name: RobotCommandName, params: dict) -> RobotCommand:
    return RobotCommand(
        command_id="cmd-bench",
        session_id="sess-bench",
        command_name=name,
        correlation_id="corr-bench",
        idempotency_key="idem-bench",
        parameters=params,
        status=CommandStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
    )


def _event(event_type: str, payload: dict) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        correlation_id="corr-bench",
        session_id="sess-bench",
        command_id="cmd-bench",
        occurred_at=datetime.now(timezone.utc),
        payload=payload,
    )


# --- Report cases: realistic completion events the ReportAgent feeds the LLM ---------
REPORT_CASES = [
    {
        "name": "sim_pass_with_verdict",
        "command": _cmd(RobotCommandName.START_SIMULATION, {"agv_count": 5}),
        "event": _event(
            "robot.command.completed",
            {
                "status": "completed",
                "kpis": {"throughput": 78.0, "avg_wait_sec": 9.4, "collisions": 0, "utilization": 0.82},
                "verdict": {
                    "passed": True,
                    "checks": [
                        {"label": "throughput >= 70/h", "passed": True, "actual": 78.0},
                        {"label": "avg_wait <= 12s", "passed": True, "actual": 9.4},
                        {"label": "collisions == 0", "passed": True, "actual": 0},
                    ],
                },
            },
        ),
        "evaluation": (
            "전체 등급: 우수. 혼잡 히트맵: 스테이션 3 주변에 경미한 정체, 나머지 구역은 고르게 분산. "
            "처리량 78/h는 목표 70을 상회. 평균 대기 9.4초로 양호. 충돌 0건."
        ),
    },
    {
        "name": "sim_fail_with_verdict",
        "command": _cmd(RobotCommandName.START_SIMULATION, {"agv_count": 8}),
        "event": _event(
            "robot.command.completed",
            {
                "status": "completed",
                "kpis": {"throughput": 61.0, "avg_wait_sec": 18.7, "collisions": 3, "utilization": 0.91},
                "verdict": {
                    "passed": False,
                    "checks": [
                        {"label": "throughput >= 70/h", "passed": False, "actual": 61.0},
                        {"label": "avg_wait <= 12s", "passed": False, "actual": 18.7},
                        {"label": "collisions == 0", "passed": False, "actual": 3},
                    ],
                },
            },
        ),
        "evaluation": (
            "전체 등급: 미흡. 혼잡 히트맵: 스테이션 2-4 구간에 심한 병목 집중. AGV 8대 투입으로 통로 경합 증가. "
            "처리량 61/h로 목표 미달, 평균 대기 18.7초로 초과, 충돌 3건 발생."
        ),
    },
    {
        "name": "station_task_complete",
        "command": _cmd(RobotCommandName.RUN_STATION_TASK, {"station_id": 3}),
        "event": _event(
            "robot.command.completed",
            {"status": "completed", "station_id": 3, "progress": 100},
        ),
        "evaluation": None,
    },
    {
        "name": "command_failed",
        "command": _cmd(RobotCommandName.INSPECT_STATION, {"station_id": 5}),
        "event": _event(
            "robot.command.failed",
            {"status": "failed", "station_id": 5, "reason": "station 5 occupied by another AGV"},
        ),
        "evaluation": None,
    },
]

# --- Chat cases: general conversational turns (no control execution) -----------------
CHAT_CASES = [
    {"name": "greeting", "history": [], "message": "안녕하세요, 당신은 무엇을 할 수 있나요?"},
    {"name": "explain_kpi", "history": [], "message": "처리량(throughput)이랑 평균 대기시간이 뭐가 다른지 설명해줘."},
    {
        "name": "followup_context",
        "history": [
            {"role": "user", "content": "방금 시뮬레이션 결과가 불합격이었어."},
            {"role": "assistant", "content": "네, 처리량이 목표에 미달했습니다."},
        ],
        "message": "그럼 다음엔 뭘 바꿔서 다시 돌려보면 좋을까?",
    },
    {"name": "off_topic_guard", "history": [], "message": "오늘 점심 메뉴 추천해줘."},
]


async def run_reports(gw, label):
    out = []
    for c in REPORT_CASES:
        t0 = time.perf_counter()
        try:
            text = await gw.generate_report(c["event"], c["command"], "corr-bench", evaluation=c["evaluation"])
            err = None
        except Exception as e:  # noqa: BLE001
            text, err = "", f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        out.append({"case": c["name"], "latency_s": round(dt, 2), "error": err, "text": text})
        print(f"  [{label}] report/{c['name']}: {dt:.2f}s {'ERR '+err if err else 'ok'}")
    return out


async def run_chats(gw, label):
    out = []
    for c in CHAT_CASES:
        t0 = time.perf_counter()
        try:
            text = await gw.generate_chat_response(c["message"], c["history"], "corr-bench")
            err = None
        except Exception as e:  # noqa: BLE001
            text, err = "", f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        out.append({"case": c["name"], "latency_s": round(dt, 2), "error": err, "text": text})
        print(f"  [{label}] chat/{c['name']}: {dt:.2f}s {'ERR '+err if err else 'ok'}")
    return out


async def main():
    standard = OllamaLlmGateway(
        base_url=OLLAMA_URL, model=OLLAMA_MODEL, timeout_seconds=120,
        num_ctx=2048, report_num_predict=512,
    )
    sft = LlamaCppLlmGateway(
        base_url=SFT_URL, model="vcore-path-action-router.gguf", timeout_seconds=120,
        num_ctx=8192, report_num_predict=512,
    )

    results = {"standard": {}, "sft": {}}
    print("REPORTS")
    results["standard"]["reports"] = await run_reports(standard, "STD")
    results["sft"]["reports"] = await run_reports(sft, "SFT")
    print("CHAT")
    results["standard"]["chats"] = await run_chats(standard, "STD")
    results["sft"]["chats"] = await run_chats(sft, "SFT")

    out_path = "../../../docs/sft/integrated/data/compare_chat_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("wrote", out_path)


if __name__ == "__main__":
    asyncio.run(main())
