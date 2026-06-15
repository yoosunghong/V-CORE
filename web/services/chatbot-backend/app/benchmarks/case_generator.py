"""Template + slot-expansion generator for the v2 benchmark suite.

Primary generation layer from plan section 2.5: deterministic, reviewable
templates with slots that expand into concrete ``BenchmarkCaseV2`` rows. The
committed JSONL under ``docs/benchmark/cases/v2/`` is the source of truth; this
module only *emits* it. Gold tool/args are constructed here (never scraped from
the weak model), so labels are known by construction.
"""

from __future__ import annotations

import re
from typing import Any

from app.benchmarks.cases_v2 import CATEGORIES, BenchmarkCaseV2

_PLACEHOLDER = re.compile(r"^\{(\w+)\}$")


def _subst(value: Any, slots: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value)
        if match and match.group(1) in slots:
            return slots[match.group(1)]  # preserve slot type (int/float)
        return value.format(**slots) if "{" in value else value
    if isinstance(value, dict):
        return {key: _subst(sub, slots) for key, sub in value.items()}
    if isinstance(value, list):
        return [_subst(item, slots) for item in value]
    return value


def _expand(template: dict[str, Any], start_index: int) -> list[BenchmarkCaseV2]:
    slot_defs: dict[str, list[Any]] = template.get("slots", {}) or {}
    combos: list[dict[str, Any]] = [{}]
    for name, options in slot_defs.items():
        combos = [{**combo, name: option} for combo in combos for option in options]

    cases: list[BenchmarkCaseV2] = []
    for offset, slots in enumerate(combos):
        idx = start_index + offset
        cases.append(
            BenchmarkCaseV2(
                case_id=f"{template['category']}_{template['lang']}_{idx:03d}",
                category=template["category"],
                lang=template["lang"],
                prompt=_subst(template["prompt"], slots),
                expected_tool=template.get("tool"),
                expected_args=_subst(template.get("args"), slots) if template.get("args") else None,
                arg_match=template.get("arg_match", "subset"),
                accept_alternatives=tuple(template.get("accept_alternatives", ())),
                expect_clarification=bool(template.get("expect_clarification", False)),
                difficulty=template.get("difficulty", "normal"),
                notes=template.get("notes", ""),
            )
        )
    return cases


# Acceptance gold fragments reused across KPI templates.
_ACC_THROUGHPUT = {"metric": "throughput", "comparator": ">=", "threshold": 70}
_ACC_WAIT = {"metric": "avg_wait_sec", "comparator": "<=", "threshold": 12}
_ACC_ZERO_COLLISION = {"metric": "collision_count", "comparator": "==", "threshold": 0}


TEMPLATES: list[dict[str, Any]] = [
    # 1. positive_invocation -------------------------------------------------
    {"category": "positive_invocation", "lang": "en", "tool": "stop_simulation",
     "prompt": "Stop the simulation."},
    {"category": "positive_invocation", "lang": "en", "tool": "pause_simulation",
     "prompt": "Pause the run."},
    {"category": "positive_invocation", "lang": "en", "tool": "resume_simulation",
     "prompt": "Resume the simulation."},
    {"category": "positive_invocation", "lang": "en", "tool": "inspect_station",
     "prompt": "Inspect station {s}.", "args": {"station_id": "{s}"}, "slots": {"s": [2, 6]}},
    {"category": "positive_invocation", "lang": "en", "tool": "start_simulation",
     "prompt": "Start the simulation with {n} AGVs.", "args": {"agv_count": "{n}"},
     "slots": {"n": [3, 5]}},
    {"category": "positive_invocation", "lang": "ko", "tool": "stop_simulation",
     "prompt": "시뮬레이션 정지해줘."},
    {"category": "positive_invocation", "lang": "ko", "tool": "pause_simulation",
     "prompt": "시뮬레이션 일시정지."},
    {"category": "positive_invocation", "lang": "ko", "tool": "resume_simulation",
     "prompt": "시뮬레이션 재개해줘."},
    {"category": "positive_invocation", "lang": "ko", "tool": "inspect_station",
     "prompt": "스테이션 {s} 검사해줘.", "args": {"station_id": "{s}"}, "slots": {"s": [3, 8]}},
    {"category": "positive_invocation", "lang": "ko", "tool": "start_simulation",
     "prompt": "AGV {n}대로 시뮬레이션 시작해.", "args": {"agv_count": "{n}"}, "slots": {"n": [3, 4]}},

    # 2. negative_control (expected_tool None) -------------------------------
    {"category": "negative_control", "lang": "en", "tool": None,
     "prompt": "{q}", "slots": {"q": [
         "What is the current process status?",
         "What can you do?",
         "Hi there.",
         "How does the AGV cell work?",
         "What's the weather today?",
         "Tell me a joke.",
         "Thanks for your help.",
         "What actions are available for station 2?",
     ]}},
    {"category": "negative_control", "lang": "ko", "tool": None,
     "prompt": "{q}", "slots": {"q": [
         "현재 공정 상태 어때?",
         "뭐 할 수 있어?",
         "안녕하세요.",
         "AGV 셀이 어떻게 동작하나요?",
         "오늘 날씨 어때?",
         "고마워요.",
     ]}},

    # 3. ambiguous (expect clarification, no tool) --------------------------
    {"category": "ambiguous", "lang": "en", "tool": None, "expect_clarification": True,
     "arg_match": "ignore", "difficulty": "hard", "prompt": "{q}", "slots": {"q": [
         "Can you handle that one over there?",
         "Do the thing.",
         "Take care of it.",
         "Start it.",
         "Go ahead with that.",
         "Sort this out for me.",
     ]}},
    {"category": "ambiguous", "lang": "ko", "tool": None, "expect_clarification": True,
     "arg_match": "ignore", "difficulty": "hard", "prompt": "{q}", "slots": {"q": [
         "저거 처리해줘.",
         "그거 해줘.",
         "알아서 해줘.",
         "저쪽 거 좀 봐줘.",
     ]}},

    # 4. parameter_extraction (single arg, exact) ---------------------------
    {"category": "parameter_extraction", "lang": "en", "tool": "move_to_station",
     "arg_match": "exact", "prompt": "Move the AGV to station {s}.",
     "args": {"station_id": "{s}"}, "slots": {"s": [1, 7, 12]}},
    {"category": "parameter_extraction", "lang": "en", "tool": "set_sim_speed",
     "arg_match": "exact", "prompt": "Set speed to {x}x.",
     "args": {"speed_multiplier": "{x}"}, "slots": {"x": [1.5, 2.0]}},
    {"category": "parameter_extraction", "lang": "ko", "tool": "move_to_station",
     "arg_match": "exact", "prompt": "AGV를 스테이션 {s}으로 이동해.",
     "args": {"station_id": "{s}"}, "slots": {"s": [2, 9]}},
    {"category": "parameter_extraction", "lang": "ko", "tool": "set_sim_speed",
     "arg_match": "exact", "prompt": "속도를 {x}배로 설정해.",
     "args": {"speed_multiplier": "{x}"}, "slots": {"x": [0.5, 3.0]}},
    {"category": "parameter_extraction", "lang": "ko", "tool": "inspect_station",
     "arg_match": "exact", "prompt": "스테이션 {s} 검사해.",
     "args": {"station_id": "{s}"}, "slots": {"s": [4, 11]}},

    # 5. multi_parameter ----------------------------------------------------
    {"category": "multi_parameter", "lang": "en", "tool": "start_simulation",
     "difficulty": "hard",
     "prompt": "Start a sim with {n} AGVs at {x}x speed named {name}.",
     "args": {"agv_count": "{n}", "speed_multiplier": "{x}", "simulation_name": "{name}"},
     "slots": {"n": [5, 8], "x": [1.5], "name": ["NightShift", "DayRun"]}},
    {"category": "multi_parameter", "lang": "en", "tool": "run_station_task",
     "prompt": "Run the task at station {s} with high priority.",
     "args": {"station_id": "{s}", "priority": "high"}, "slots": {"s": [2, 5]}},
    {"category": "multi_parameter", "lang": "ko", "tool": "start_simulation",
     "difficulty": "hard", "prompt": "AGV {n}대로 {x}배속 시뮬레이션 시작해.",
     "args": {"agv_count": "{n}", "speed_multiplier": "{x}"},
     "slots": {"n": [4, 6], "x": [2.0]}},
    {"category": "multi_parameter", "lang": "ko", "tool": "run_station_task",
     "prompt": "스테이션 {s} 작업을 높은 우선순위로 실행해.",
     "args": {"station_id": "{s}", "priority": "high"}, "slots": {"s": [3, 7]}},

    # 6. missing_parameter (required arg absent -> clarify, no tool) --------
    {"category": "missing_parameter", "lang": "en", "tool": None, "expect_clarification": True,
     "arg_match": "ignore", "prompt": "{q}", "slots": {"q": [
         "Move the AGV.",
         "Run the task.",
         "Set the speed.",
         "Inspect the station.",
         "Send the AGV over.",
         "Go run a task.",
     ]}},
    {"category": "missing_parameter", "lang": "ko", "tool": None, "expect_clarification": True,
     "arg_match": "ignore", "prompt": "{q}", "slots": {"q": [
         "AGV 이동해줘.",
         "작업 실행해.",
         "속도 바꿔줘.",
         "스테이션 검사해.",
         "거기로 보내줘.",
         "작업 좀 돌려.",
     ]}},

    # 7. long_request (single intent buried in noise) -----------------------
    {"category": "long_request", "lang": "en", "tool": "start_simulation", "difficulty": "hard",
     "prompt": ("We had a rough morning shift, throughput dipped and the floor was a mess, "
                "anyway can you just go ahead and restart the simulation with the usual {n} AGVs."),
     "args": {"agv_count": "{n}"}, "slots": {"n": [3, 4]}},
    {"category": "long_request", "lang": "en", "tool": "set_sim_speed", "difficulty": "hard",
     "prompt": ("The presentation is running long and people are getting restless, so I think "
                "it would help if you bumped the simulation speed up to {x}x for the rest of it."),
     "args": {"speed_multiplier": "{x}"}, "slots": {"x": [2.0, 3.0]}},
    {"category": "long_request", "lang": "ko", "tool": "start_simulation", "difficulty": "hard",
     "prompt": ("아침 교대 때 처리량이 좀 떨어졌고 현장이 정신없었는데, 어쨌든 그냥 평소처럼 "
                "AGV {n}대로 시뮬레이션 다시 시작해줘."),
     "args": {"agv_count": "{n}"}, "slots": {"n": [3, 5]}},
    {"category": "long_request", "lang": "en", "tool": "move_to_station", "difficulty": "hard",
     "prompt": ("Okay so after the last run we noticed AGV idling near the dock, could you "
                "just move the AGV over to station {s} so we can take a closer look."),
     "args": {"station_id": "{s}"}, "slots": {"s": [6, 9]}},
    {"category": "long_request", "lang": "ko", "tool": "move_to_station", "difficulty": "hard",
     "prompt": ("지난 런에서 도크 근처에 AGV가 멈춰 있는 걸 봤는데, 자세히 보게 그냥 "
                "AGV를 스테이션 {s}으로 옮겨줘."),
     "args": {"station_id": "{s}"}, "slots": {"s": [4, 8]}},

    # 8. kpi_acceptance (nested acceptance array) ---------------------------
    {"category": "kpi_acceptance", "lang": "en", "tool": "start_simulation", "difficulty": "hard",
     "prompt": ("Start with {n} AGVs and accept only if throughput is at least 70 per hour, "
                "average wait is under 12 seconds, and collisions are zero."),
     "args": {"agv_count": "{n}", "acceptance": [_ACC_THROUGHPUT, _ACC_WAIT, _ACC_ZERO_COLLISION]},
     "slots": {"n": [4, 6]}},
    {"category": "kpi_acceptance", "lang": "en", "tool": "start_simulation", "difficulty": "hard",
     "prompt": "Run {n} AGVs and pass only if there are zero collisions.",
     "args": {"agv_count": "{n}", "acceptance": [_ACC_ZERO_COLLISION]},
     "slots": {"n": [3, 5]}},
    {"category": "kpi_acceptance", "lang": "ko", "tool": "start_simulation", "difficulty": "hard",
     "prompt": ("처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 "
                "AGV {n}대 돌려줘."),
     "args": {"agv_count": "{n}", "acceptance": [_ACC_THROUGHPUT, _ACC_WAIT, _ACC_ZERO_COLLISION]},
     "slots": {"n": [4, 8]}},
    {"category": "kpi_acceptance", "lang": "ko", "tool": "start_simulation", "difficulty": "hard",
     "prompt": "충돌 0건이면 통과로 AGV {n}대 시뮬레이션 시작해.",
     "args": {"agv_count": "{n}", "acceptance": [_ACC_ZERO_COLLISION]},
     "slots": {"n": [3, 6]}},
    {"category": "kpi_acceptance", "lang": "en", "tool": "start_simulation", "difficulty": "hard",
     "prompt": "Launch {n} AGVs, accept the run only if throughput stays at or above 70 per hour.",
     "args": {"agv_count": "{n}", "acceptance": [_ACC_THROUGHPUT]},
     "slots": {"n": [4, 7]}},

    # 9. invalid_parameter (best behavior = decline, don't silently pass) ---
    {"category": "invalid_parameter", "lang": "en", "tool": None, "expect_clarification": True,
     "arg_match": "ignore", "difficulty": "hard", "prompt": "{q}", "slots": {"q": [
         "Move to station -1.",
         "Set the speed to 0.",
         "Set the speed to -2x.",
         "Start with 'five' AGVs.",
         "Inspect station 999.",
     ]}},
    {"category": "invalid_parameter", "lang": "ko", "tool": None, "expect_clarification": True,
     "arg_match": "ignore", "difficulty": "hard", "prompt": "{q}", "slots": {"q": [
         "스테이션 -1로 이동해.",
         "속도를 0으로 설정해.",
         "AGV '다섯'대로 시작해.",
         "스테이션 999 검사해.",
         "속도를 -2배로 해줘.",
     ]}},

    # 10. disambiguation (same station, verb selects tool) ------------------
    {"category": "disambiguation", "lang": "en", "tool": "move_to_station", "arg_match": "exact",
     "prompt": "Go to station {s}.", "args": {"station_id": "{s}"}, "slots": {"s": [3, 10]}},
    {"category": "disambiguation", "lang": "en", "tool": "run_station_task",
     "prompt": "Work station {s}.", "args": {"station_id": "{s}"}, "slots": {"s": [3, 10]}},
    {"category": "disambiguation", "lang": "en", "tool": "inspect_station", "arg_match": "exact",
     "prompt": "Check station {s}.", "args": {"station_id": "{s}"}, "slots": {"s": [3, 10]}},
    {"category": "disambiguation", "lang": "ko", "tool": "move_to_station", "arg_match": "exact",
     "prompt": "스테이션 {s}으로 가.", "args": {"station_id": "{s}"}, "slots": {"s": [5, 9]}},
    {"category": "disambiguation", "lang": "ko", "tool": "run_station_task",
     "prompt": "스테이션 {s} 작업해.", "args": {"station_id": "{s}"}, "slots": {"s": [5, 9]}},
    {"category": "disambiguation", "lang": "ko", "tool": "inspect_station", "arg_match": "exact",
     "prompt": "스테이션 {s} 확인해.", "args": {"station_id": "{s}"}, "slots": {"s": [5, 9]}},

    # 11. sequential (score the first actionable tool) ----------------------
    {"category": "sequential", "lang": "en", "tool": "move_to_station",
     "prompt": "Move to station {s}, then run the task there.",
     "args": {"station_id": "{s}"}, "slots": {"s": [2, 8]},
     "notes": "single-call limitation: first action only"},
    {"category": "sequential", "lang": "en", "tool": "pause_simulation", "arg_match": "ignore",
     "prompt": "Pause it, then set speed to 0.5x.",
     "notes": "single-call limitation: first action only"},
    {"category": "sequential", "lang": "en", "tool": "start_simulation", "arg_match": "ignore",
     "prompt": "Start a sim and then stop it after a minute.",
     "notes": "single-call limitation: first action only"},
    {"category": "sequential", "lang": "ko", "tool": "move_to_station",
     "prompt": "스테이션 {s}으로 이동한 다음 거기서 작업 실행해.",
     "args": {"station_id": "{s}"}, "slots": {"s": [3, 7]},
     "notes": "single-call limitation: first action only"},
    {"category": "sequential", "lang": "ko", "tool": "pause_simulation", "arg_match": "ignore",
     "prompt": "일시정지하고 나서 속도를 0.5배로 바꿔.",
     "notes": "single-call limitation: first action only"},
    {"category": "sequential", "lang": "en", "tool": "inspect_station",
     "prompt": "Inspect station {s} first, then run the task on it.",
     "args": {"station_id": "{s}"}, "slots": {"s": [4, 9]},
     "notes": "single-call limitation: first action only"},
    {"category": "sequential", "lang": "ko", "tool": "stop_simulation", "arg_match": "ignore",
     "prompt": "먼저 정지하고 그 다음에 재시작해줘.",
     "notes": "single-call limitation: first action only"},

    # 12. state_dependent (propose the coherent lifecycle command) ----------
    {"category": "state_dependent", "lang": "en", "tool": "resume_simulation", "arg_match": "ignore",
     "prompt": "Resume.", "notes": "coherent if a sim is paused"},
    {"category": "state_dependent", "lang": "en", "tool": "stop_simulation", "arg_match": "ignore",
     "prompt": "Stop.", "notes": "coherent if a sim is running"},
    {"category": "state_dependent", "lang": "en", "tool": "pause_simulation", "arg_match": "ignore",
     "prompt": "Pause it for now.", "notes": "coherent mid-run"},
    {"category": "state_dependent", "lang": "en", "tool": "resume_simulation", "arg_match": "ignore",
     "prompt": "Pick it back up where we left off.", "notes": "coherent if paused"},
    {"category": "state_dependent", "lang": "ko", "tool": "resume_simulation", "arg_match": "ignore",
     "prompt": "다시 진행해.", "notes": "coherent if paused"},
    {"category": "state_dependent", "lang": "ko", "tool": "stop_simulation", "arg_match": "ignore",
     "prompt": "이제 멈춰.", "notes": "coherent if running"},
    {"category": "state_dependent", "lang": "ko", "tool": "pause_simulation", "arg_match": "ignore",
     "prompt": "잠깐 멈춰둬.", "notes": "coherent mid-run"},
    {"category": "state_dependent", "lang": "en", "tool": "stop_simulation", "arg_match": "ignore",
     "prompt": "That's enough, shut it down.", "notes": "coherent if running"},
    {"category": "state_dependent", "lang": "en", "tool": "pause_simulation", "arg_match": "ignore",
     "prompt": "Hold on, freeze the run.", "notes": "coherent mid-run"},
    {"category": "state_dependent", "lang": "ko", "tool": "resume_simulation", "arg_match": "ignore",
     "prompt": "이어서 계속해.", "notes": "coherent if paused"},
]


def build_cases_by_category() -> dict[str, list[BenchmarkCaseV2]]:
    grouped: dict[str, list[BenchmarkCaseV2]] = {category: [] for category in CATEGORIES}
    for template in TEMPLATES:
        category = template["category"]
        cases = _expand(template, start_index=len(grouped[category]) + 1)
        grouped[category].extend(cases)
    return grouped


def build_all_cases() -> list[BenchmarkCaseV2]:
    grouped = build_cases_by_category()
    cases: list[BenchmarkCaseV2] = []
    for category in CATEGORIES:
        cases.extend(grouped[category])
    return cases
