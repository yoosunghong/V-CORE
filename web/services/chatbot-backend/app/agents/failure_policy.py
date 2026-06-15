from __future__ import annotations

from app.tools.contracts import ToolValidationError


class LlmGatewayError(RuntimeError):
    pass


class LlmTimeoutError(LlmGatewayError):
    pass


class AgentFailurePolicy:
    def ambiguous_command_message(self) -> str:
        return (
            "요청을 실행 명령으로 확정하기 어렵습니다. "
            "예: '시뮬레이션 시작해줘', '속도 4배로 바꿔', "
            "'1번 스테이션으로 보내', '2번 스테이션 작업해줘'처럼 "
            "작업 종류와 대상을 함께 알려주세요."
        )

    def llm_unavailable_message(self) -> str:
        return "현재 LLM 응답을 받을 수 없어 AGV 명령을 발행하지 못했습니다. 잠시 후 다시 시도해 주세요."

    def invalid_tool_message(self, error: ToolValidationError) -> str:
        return f"LLM 도구 호출 형식이 안전 검증을 통과하지 못했습니다. 사유: {error}"

    def command_not_allowed_message(self, station_id: int) -> str:
        return f"{station_id}번 스테이션은 현재 작업 가능한 상태가 아니어서 AGV 명령을 발행하지 않았습니다."
