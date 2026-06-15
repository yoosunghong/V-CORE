from __future__ import annotations

_START_KEYWORDS = (
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
)


class RuleBasedPlanningFallback:
    def _is_simulation_start(self, normalized: str, user_message: str) -> bool:
        if "취소" in user_message or "정지" in user_message or "중단" in user_message:
            return False
        return any(keyword in normalized for keyword in _START_KEYWORDS)

    def build_steps(self, user_message: str) -> list[str]:
        normalized = user_message.lower()
        if "telemetry" in normalized or "process status" in normalized:
            return [
                "요청이 가상 공정 상태 확인인지 판단합니다.",
                "UE5 시뮬레이션에서 최신 처리량, 가동률, 대기시간, 충돌 위험 지표를 조회합니다.",
                "작업 명령 없이 상태 요약만 사용자에게 보고합니다.",
            ]
        if "cancel" in normalized:
            return [
                "요청이 진행 중인 AGV 작업 취소인지 판단합니다.",
                "세션에서 가장 최근의 취소 가능한 command_id를 찾습니다.",
                "취소 도구 호출을 검증한 뒤 UE5 공정으로 전달합니다.",
            ]
        if self._is_simulation_start(normalized, user_message):
            return [
                "요청에서 AGV 대수와 처리량·대기시간·충돌 같은 합격 기준(목표 KPI)을 추출합니다.",
                "start_simulation 도구 인자(agv_count, acceptance)를 스키마로 검증합니다.",
                "UE5 가상 공정에 AGV를 배치하고 시뮬레이션을 시작합니다.",
                "실시간 진행/리플레이 이벤트와 KPI 텔레메트리를 추적합니다.",
                "완료 시 최종 KPI를 합격 기준과 대조해 합격/불합격 결과를 보고합니다.",
            ]
        if "simulation" in normalized or "시뮬레이션" in user_message:
            return [
                "요청이 시뮬레이션 수명주기 제어(시작/정지/일시정지/속도)인지 판단합니다.",
                "해당 도구 호출 인자를 스키마로 검증합니다.",
                "검증된 명령을 UE5 가상 공정에 발행하고 진행 이벤트를 추적합니다.",
            ]
        return [
            "요청에서 대상 스테이션과 의도를 추론합니다.",
            "가능한 실행 경로 중 작업, 이동, 점검, 취소 중 가장 적합한 플랜을 선택합니다.",
            "선택한 도구 호출 인자를 스키마로 검증합니다.",
            "검증된 AGV 명령을 UE5 가상 공정에 발행하고 진행 이벤트를 추적합니다.",
        ]
