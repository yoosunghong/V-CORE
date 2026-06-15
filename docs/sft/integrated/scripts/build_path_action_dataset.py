"""Build the integrated path/action SFT dataset.

This experiment trains one structured decision model to do both layers that the
current backend keeps separate:

    route selection -> optional robot action selection -> arguments

The label is intentionally not a chat/report response. It is a control-plane JSON
envelope suitable for benchmarking a single llama.cpp-served model:

    {"route": "process_status", "action": null, "arguments": {}}
    {"route": "robot_command", "action": "start_simulation", "arguments": {...}}

Run:
    C:/Users/PC/anaconda3/python.exe docs/sft/integrated/scripts/build_path_action_dataset.py
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

SEED = 20260615
random.seed(SEED)

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "docs" / "sft" / "integrated" / "data"
OUT.mkdir(parents=True, exist_ok=True)

ROBOT_ACTIONS = {
    "move_to_station",
    "run_station_task",
    "inspect_station",
    "cancel_command",
    "start_simulation",
    "stop_simulation",
    "pause_simulation",
    "resume_simulation",
    "set_sim_speed",
}
ROUTES = {
    "process_status",
    "simulation_status",
    "station_action_query",
    "compare_runs",
    "optimize_agvs",
    "robot_command",
    "clarify",
    "no_action",
}

STATIONS = list(range(1, 13))
AGV_COUNTS = [2, 3, 4, 5, 6, 8]
SPEEDS = [0.5, 1.0, 1.5, 2.0, 3.0]
COMMAND_IDS = ["cmd-101", "cmd-204", "run-88", "sim-77"]

SUFFIX_EN = ["", " please", " now", " right away", " for the demo", " in the cell", " for me", " this turn"]
SUFFIX_KO = ["", " 지금", " 바로", " 부탁해", " 데모용으로", " 셀 기준으로", " 이번 턴에", " 간단히"]


def label(route: str, action: str | None = None, args: dict | None = None) -> dict:
    if route not in ROUTES:
        raise ValueError(route)
    if route == "robot_command" and action not in ROBOT_ACTIONS:
        raise ValueError(action)
    if route != "robot_command" and action is not None:
        raise ValueError(f"{route} cannot carry action {action}")
    return {"route": route, "action": action, "arguments": args or {}}


def row(prompt: str, category: str, lang: str, completion: dict) -> dict:
    return {
        "prompt": prompt,
        "category": category,
        "lang": lang,
        "completion": completion,
    }


def suffixed(text: str, lang: str) -> str:
    suffix = random.choice(SUFFIX_KO if lang == "ko" else SUFFIX_EN)
    return f"{text}{suffix}" if suffix else text


def station_text(n: int, lang: str) -> str:
    if lang == "ko":
        return random.choice([f"{n}번 스테이션", f"스테이션 {n}", f"{n}번 작업대"])
    return random.choice([f"station {n}", f"S{n}", f"workstation {n}", f"station number {n}"])


def make_unique(target: int, category: str, factory, seen: set[str]) -> list[dict]:
    out: list[dict] = []
    guard = 0
    while len(out) < target and guard < target * 400:
        guard += 1
        item = factory()
        if item["prompt"] in seen:
            continue
        seen.add(item["prompt"])
        out.append(item)
    if len(out) != target:
        raise RuntimeError(f"{category} exhausted: {len(out)}/{target}")
    return out


def f_process_status() -> dict:
    lang = random.choice(["en", "ko"])
    prompt = random.choice(
        [
            "What is the current process status?",
            "Show me the current KPI snapshot.",
            "How is the cell doing right now?",
            "Tell me throughput and waiting time.",
            "Current process telemetry.",
        ]
        if lang == "en"
        else [
            "현재 공정 상태 알려줘.",
            "지금 KPI 보여줘.",
            "처리량이랑 대기시간 알려줘.",
            "현재 공정 텔레메트리 확인해줘.",
            "공정 상태 요약해줘.",
        ]
    )
    return row(suffixed(prompt, lang), "process_status", lang, label("process_status"))


def f_simulation_status() -> dict:
    lang = random.choice(["en", "ko"])
    prompt = random.choice(
        [
            "Show current AGV positions.",
            "Which AGVs are active right now?",
            "Give me the live simulation status.",
            "Where are the robots in the cell?",
            "Show the running simulation state.",
        ]
        if lang == "en"
        else [
            "현재 AGV 위치 보여줘.",
            "지금 어떤 AGV가 움직이고 있어?",
            "라이브 시뮬레이션 상태 알려줘.",
            "로봇들이 어디 있는지 보여줘.",
            "실행 중인 시뮬레이션 상태 확인해줘.",
        ]
    )
    return row(suffixed(prompt, lang), "simulation_status", lang, label("simulation_status"))


def f_station_action_query() -> dict:
    lang = random.choice(["en", "ko"])
    n = random.choice(STATIONS)
    st = station_text(n, lang)
    prompt = random.choice(
        [
            f"What can {st} do?",
            f"Which actions are available for {st}?",
            f"Tell me the task options at {st}.",
            f"Can {st} be inspected or worked?",
        ]
        if lang == "en"
        else [
            f"{st}에서 가능한 작업 알려줘.",
            f"{st} 액션 목록 보여줘.",
            f"{st}는 어떤 작업을 할 수 있어?",
            f"{st}에서 검사나 작업 가능해?",
        ]
    )
    return row(suffixed(prompt, lang), "station_action_query", lang, label("station_action_query"))


def f_compare_runs() -> dict:
    lang = random.choice(["en", "ko"])
    prompt = random.choice(
        [
            "Compare the last two runs.",
            "Which recent simulation was better?",
            "Compare run A and run B.",
            "Show me the difference between the previous runs.",
            "Tell me whether the latest run improved.",
        ]
        if lang == "en"
        else [
            "최근 두 번 실행 결과 비교해줘.",
            "어떤 시뮬레이션이 더 나았어?",
            "이전 실행과 최신 실행 비교해줘.",
            "두 실행의 차이를 알려줘.",
            "마지막 실행이 개선됐는지 비교해줘.",
        ]
    )
    return row(suffixed(prompt, lang), "compare_runs", lang, label("compare_runs"))


def f_optimize_agvs() -> dict:
    lang = random.choice(["en", "ko"])
    metric = random.choice(["bottleneck rate", "throughput", "average wait", "collisions"])
    prompt = random.choice(
        [
            f"Find the best AGV count for {metric}.",
            f"Optimize the number of AGVs to reduce {metric}.",
            "How many AGVs should I use for the best KPI?",
            "Search for the optimal fleet size.",
            "Recommend the AGV count that meets the target.",
        ]
        if lang == "en"
        else [
            "최적 AGV 대수 찾아줘.",
            "병목률 줄이려면 AGV 몇 대가 좋아?",
            "KPI가 제일 좋은 AGV 수 추천해줘.",
            "최적 운행 대수를 계산해줘.",
            "목표를 만족하는 AGV 대수 찾아줘.",
        ]
    )
    return row(suffixed(prompt, lang), "optimize_agvs", lang, label("optimize_agvs"))


def f_move() -> dict:
    lang = random.choice(["en", "ko"])
    n = random.choice(STATIONS)
    st = station_text(n, lang)
    prompt = random.choice(
        [f"Move the AGV to {st}.", f"Send the robot to {st}.", f"Drive to {st}.", f"Dispatch the AGV to {st}."]
        if lang == "en"
        else [f"AGV를 {st}으로 이동해.", f"로봇을 {st}으로 보내줘.", f"{st}으로 이동시켜.", f"AGV {st}으로 보내."]
    )
    return row(suffixed(prompt, lang), "move_to_station", lang, label("robot_command", "move_to_station", {"station_id": n}))


def f_run() -> dict:
    lang = random.choice(["en", "ko"])
    n = random.choice(STATIONS)
    high = random.random() < 0.3
    st = station_text(n, lang)
    prompt = random.choice(
        [f"Run the task at {st}.", f"Work {st}.", f"Execute the job at {st}.", f"Start the process at {st}."]
        if lang == "en"
        else [f"{st} 작업해.", f"{st} 작업 실행해.", f"{st}에서 공정 수행해.", f"{st} 작업 돌려."]
    )
    args = {"station_id": n}
    if high:
        args["priority"] = "high"
        prompt += " High priority." if lang == "en" else " 높은 우선순위로."
    return row(suffixed(prompt, lang), "run_station_task", lang, label("robot_command", "run_station_task", args))


def f_inspect() -> dict:
    lang = random.choice(["en", "ko"])
    n = random.choice(STATIONS)
    st = station_text(n, lang)
    prompt = random.choice(
        [f"Inspect {st}.", f"Check {st}.", f"Look at {st}.", f"Examine {st}."]
        if lang == "en"
        else [f"{st} 확인해.", f"{st} 검사해.", f"{st} 상태 봐줘.", f"{st} 점검해."]
    )
    return row(suffixed(prompt, lang), "inspect_station", lang, label("robot_command", "inspect_station", {"station_id": n}))


def f_sim_action() -> dict:
    lang = random.choice(["en", "ko"])
    pick = random.choice(["start", "start_speed", "stop", "pause", "resume", "speed"])
    if pick == "start":
        n = random.choice(AGV_COUNTS)
        prompt = random.choice(
            [f"Start the simulation with {n} AGVs.", f"Launch a run with {n} AGVs.", f"Begin using {n} AGVs."]
            if lang == "en"
            else [f"AGV {n}대로 시뮬레이션 시작해.", f"{n}대로 실행 시작해.", f"AGV {n}대로 돌려줘."]
        )
        return row(suffixed(prompt, lang), "start_simulation", lang, label("robot_command", "start_simulation", {"agv_count": n}))
    if pick == "start_speed":
        n = random.choice(AGV_COUNTS)
        speed = random.choice(SPEEDS)
        prompt = random.choice(
            [f"Start {n} AGVs at {speed}x speed.", f"Run a {speed}x simulation with {n} AGVs."]
            if lang == "en"
            else [f"AGV {n}대를 {speed}배속으로 시작해.", f"{speed}배속 {n}대 시뮬레이션 돌려줘."]
        )
        return row(suffixed(prompt, lang), "start_with_speed", lang, label("robot_command", "start_simulation", {"agv_count": n, "speed_multiplier": speed}))
    if pick == "speed":
        speed = random.choice(SPEEDS)
        prompt = random.choice(
            [f"Set speed to {speed}x.", f"Change simulation speed to {speed}x.", f"Use {speed}x speed."]
            if lang == "en"
            else [f"속도를 {speed}배로 설정해.", f"{speed}배속으로 바꿔.", f"시뮬레이션 속도 {speed}배."]
        )
        return row(suffixed(prompt, lang), "set_sim_speed", lang, label("robot_command", "set_sim_speed", {"speed_multiplier": speed}))
    mapping = {
        "stop": ("stop_simulation", ["Stop the simulation.", "Halt the run.", "Shut it down."], ["시뮬레이션 정지해.", "실행 멈춰.", "이제 중단해."]),
        "pause": ("pause_simulation", ["Pause the simulation.", "Freeze the run.", "Hold the sim."], ["시뮬레이션 일시정지.", "잠깐 멈춰.", "실행 보류해."]),
        "resume": ("resume_simulation", ["Resume the simulation.", "Continue the run.", "Pick it back up."], ["다시 진행해.", "시뮬레이션 재개.", "이어서 계속해."]),
    }
    action, en, ko = mapping[pick]
    prompt = random.choice(ko if lang == "ko" else en)
    return row(suffixed(prompt, lang), action, lang, label("robot_command", action))


def f_kpi_acceptance() -> dict:
    lang = random.choice(["en", "ko"])
    n = random.choice(AGV_COUNTS)
    throughput = random.choice([60, 65, 70, 75, 80])
    wait = random.choice([10, 12, 15])
    acc = [
        {"metric": "throughput", "comparator": ">=", "threshold": throughput},
        {"metric": "avg_wait_sec", "comparator": "<=", "threshold": wait},
        {"metric": "collision_count", "comparator": "==", "threshold": 0},
    ]
    if lang == "en":
        prompt = f"Start with {n} AGVs and pass only if throughput is at least {throughput}, average wait is under {wait} seconds, and collisions are zero."
    else:
        prompt = f"처리량 {throughput} 이상, 평균 대기 {wait}초 이하, 충돌 0건이면 통과로 AGV {n}대 돌려줘."
    return row(suffixed(prompt, lang), "kpi_acceptance", lang, label("robot_command", "start_simulation", {"agv_count": n, "acceptance": acc}))


def f_cancel() -> dict:
    lang = random.choice(["en", "ko"])
    cid = random.choice(COMMAND_IDS)
    prompt = random.choice(
        [f"Cancel command {cid}.", f"Stop job {cid}.", f"Abort command id {cid}."]
        if lang == "en"
        else [f"{cid} 명령 취소해.", f"{cid} 작업 중단해.", f"명령 {cid} 취소."]
    )
    return row(suffixed(prompt, lang), "cancel_command", lang, label("robot_command", "cancel_command", {"command_id": cid}))


def f_clarify() -> dict:
    lang = random.choice(["en", "ko"])
    prompt = random.choice(
        [
            "Move the AGV.",
            "Run the task.",
            "Inspect the station.",
            "Set the speed.",
            "Cancel the command.",
            "Send it over there.",
            "Start with five AGVs.",
            "Move to station -1.",
        ]
        if lang == "en"
        else [
            "AGV 이동해줘.",
            "작업 실행해.",
            "스테이션 검사해.",
            "속도 바꿔줘.",
            "명령 취소해.",
            "거기로 보내줘.",
            "AGV 다섯 대로 시작해.",
            "스테이션 -1로 이동해.",
        ]
    )
    return row(suffixed(prompt, lang), "clarify", lang, label("clarify"))


def f_no_action() -> dict:
    lang = random.choice(["en", "ko"])
    prompt = random.choice(
        [
            "Hi there.",
            "Tell me a joke.",
            "What is the weather today?",
            "Thanks for your help.",
            "Explain digital twins generally.",
            "What can you do?",
        ]
        if lang == "en"
        else [
            "안녕하세요.",
            "농담 하나 해줘.",
            "오늘 날씨 어때?",
            "고마워요.",
            "디지털 트윈이 뭔지 설명해줘.",
            "뭐 할 수 있어?",
        ]
    )
    return row(suffixed(prompt, lang), "no_action", lang, label("no_action"))


SPLITS = {
    "process_status": (f_process_status, 45, 8, 15),
    "simulation_status": (f_simulation_status, 36, 6, 12),
    "station_action_query": (f_station_action_query, 36, 6, 12),
    "compare_runs": (f_compare_runs, 30, 5, 10),
    "optimize_agvs": (f_optimize_agvs, 36, 6, 12),
    "move_to_station": (f_move, 42, 7, 14),
    "run_station_task": (f_run, 42, 7, 14),
    "inspect_station": (f_inspect, 36, 6, 12),
    "sim_actions": (f_sim_action, 72, 12, 24),
    "kpi_acceptance": (f_kpi_acceptance, 36, 6, 12),
    "cancel_command": (f_cancel, 18, 3, 6),
    "clarify": (f_clarify, 42, 7, 14),
    "no_action": (f_no_action, 27, 5, 9),
}


def validate(rows: list[dict]) -> None:
    prompts = [r["prompt"] for r in rows]
    if len(prompts) != len(set(prompts)):
        raise RuntimeError("duplicate prompts generated")
    for r in rows:
        c = r["completion"]
        route = c.get("route")
        action = c.get("action")
        args = c.get("arguments")
        if route not in ROUTES:
            raise RuntimeError(f"bad route: {route}")
        if not isinstance(args, dict):
            raise RuntimeError(f"bad args: {args}")
        if route == "robot_command":
            if action not in ROBOT_ACTIONS:
                raise RuntimeError(f"bad action: {action}")
        elif action is not None:
            raise RuntimeError(f"non-command action on {route}: {action}")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    seen: set[str] = set()
    splits: dict[str, list[dict]] = defaultdict(list)
    for category, (factory, train_n, val_n, test_n) in SPLITS.items():
        rows = make_unique(train_n + val_n + test_n, category, factory, seen)
        splits["train"].extend(rows[:train_n])
        splits["val"].extend(rows[train_n : train_n + val_n])
        splits["test"].extend(rows[train_n + val_n :])

    for rows in splits.values():
        random.shuffle(rows)
        validate(rows)

    for name in ("train", "val", "test"):
        write_jsonl(OUT / f"{name}.jsonl", splits[name])

    all_rows = [r for rows in splits.values() for r in rows]
    validate(all_rows)
    summary = {
        "seed": SEED,
        "total": len(all_rows),
        "splits": {name: len(rows) for name, rows in splits.items()},
        "by_category": dict(sorted(Counter(r["category"] for r in all_rows).items())),
        "by_route": dict(sorted(Counter(r["completion"]["route"] for r in all_rows).items())),
        "by_action": dict(
            sorted(Counter(r["completion"]["action"] or "null" for r in all_rows).items())
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
