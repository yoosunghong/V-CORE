"""Phase 3 SFT-1 dataset generator for V-CORE Domain Tool Routing.

Extends the 133-case v2 benchmark suite into a Train/Val/Test SFT set
(300/50/100) by template + slot expansion. Labels are constructed here
(never scraped from a weak model) so they are correct by construction and
match the *real* production tool contracts in
``web/services/chatbot-backend/app/tools/contracts.py``.

Label shape == what ``OllamaLlmGateway`` parses today:
    {"name": "<tool>", "arguments": {...}}
No-tool / clarify uses the production decline sentinels:
    negative / out-of-scope -> {"name": "none", "arguments": {}}
    missing / ambiguous / invalid -> {"name": "clarify", "arguments": {"message": ...}}

Run (host anaconda; no local python in the app env):
    C:/Users/PC/anaconda3/python.exe docs/sft/scripts/build_sft_dataset.py
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

SEED = 20260611
random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Named-area aliases -> integer station_id (documented contract for the SFT set) ---
ALIAS_MAP = {
    "loading area": 1,
    "로딩 구역": 1,
    "shipping area": 12,
    "출하 구역": 12,
    "warehouse": 10,
    "창고": 10,
}

# Surface-form banks ---------------------------------------------------------
STATION_FORMS_EN = ["S{n}", "station {n}", "workstation {n}", "station number {n}"]
STATION_FORMS_KO = ["{n}번 스테이션", "스테이션 {n}", "{n}번 작업대"]
MOVE_EN = ["Send the AGV to {st}.", "Move the AGV to {st}.", "Dispatch the AGV to {st}.",
           "Drive the robot to {st}.", "Take the AGV over to {st}."]
MOVE_KO = ["AGV를 {st}으로 보내.", "AGV를 {st}으로 이동해.", "로봇을 {st}으로 이동시켜.",
           "{st}으로 AGV 보내줘."]
RUN_EN = ["Run the task at {st}.", "Work {st}.", "Execute the job at {st}.",
          "Do the task on {st}.", "Start the process at {st}."]
RUN_KO = ["{st} 작업해.", "{st} 작업 실행해.", "{st}에서 공정 수행해.", "{st} 작업 돌려."]
INSPECT_EN = ["Check {st}.", "Inspect {st}.", "Look at {st}.", "Take a look at {st}.",
              "Examine {st}."]
INSPECT_KO = ["{st} 확인해.", "{st} 검사해.", "{st} 점검해.", "{st} 상태 봐줘."]

# Lifecycle banks
START_EN = ["Start the simulation with {n} AGVs.", "Launch a run with {n} AGVs.",
            "Begin the simulation using {n} AGVs.", "Kick off the sim with {n} AGVs."]
START_KO = ["AGV {n}대로 시뮬레이션 시작해.", "AGV {n}대로 런 시작해줘.",
            "{n}대로 시뮬레이션 돌려."]

# Compound start+speed banks — start_simulation carrying BOTH agv_count and
# speed_multiplier. The original set never paired these (every speed_multiplier label
# sat on set_sim_speed), so the model emitted out-of-distribution synonyms on
# "start at Nx with M AGVs". These templates close that gap.
START_SPEED_EN = ["Perform a {x}x speed simulation with {n} AGVs.",
                  "Start the simulation with {n} AGVs at {x}x speed.",
                  "Run {n} AGVs at {x}x speed.",
                  "Launch a run with {n} AGVs at {x}x.",
                  "Begin a {x}x simulation using {n} AGVs.",
                  "Kick off the sim with {n} AGVs at {x} times speed."]
START_SPEED_KO = ["{x}배속 {n}대로 시작해.", "AGV {n}대로 {x}배속 시뮬레이션 시작해.",
                  "{n}대로 {x}배속으로 돌려.", "{x}배 속도로 AGV {n}대 시작해줘.",
                  "{n}대 {x}배속 런 시작해."]
START_SPEED_ACC_EN = ["Start a {x}x run with {n} AGVs and accept only if {goal}.",
                      "Run {n} AGVs at {x}x speed, passing only if {goal}."]
START_SPEED_ACC_KO = ["{goal}이면 통과로 {x}배속 {n}대로 돌려줘.",
                      "{n}대 {x}배속으로 시작하고 {goal}이면 통과."]
START_SPEEDS = [1.0, 1.5, 2.0, 3.0]

# Under-covered acceptance metrics — bottleneck_rate (percent 0-100, matches the backend's
# heatmap-derived KPI), uptime_ratio (0-1), active_agvs (count). These are single-run
# *verifiable* goals that route to the tool router. They deliberately avoid optimize verbs
# (최적/찾아/몇 대/optimal/optimize/how many/best) so they do NOT trip the upstream optimizer
# (is_optimize_request requires an optimize verb AND a bottleneck word). value, comparator, bank.
ACC_METRIC_EN = {
    "bottleneck_rate": ("the bottleneck rate stays under {v}%", "<=", [10, 15, 20, 25]),
    "uptime_ratio": ("uptime ratio is at least {v}", ">=", [0.9, 0.95]),
    "active_agvs": ("at least {v} AGVs stay active", ">=", [2, 3, 4]),
}
ACC_METRIC_KO = {
    "bottleneck_rate": ("병목률이 {v}% 이하", "<=", [10, 15, 20, 25]),
    "uptime_ratio": ("가동 비율이 {v} 이상", ">=", [0.9, 0.95]),
    "active_agvs": ("가동 AGV가 {v}대 이상", ">=", [2, 3, 4]),
}
ACC_START_EN = ["Start the simulation with {n} AGVs and accept only if {goal}.",
                "Run {n} AGVs, passing only if {goal}.",
                "Begin a run with {n} AGVs; it passes only if {goal}."]
ACC_START_KO = ["{goal}이면 통과로 {n}대로 시작해.",
                "AGV {n}대로 돌리고 {goal}이면 통과.",
                "{n}대로 시작하고 {goal}이면 합격."]
SIMPLE_LIFECYCLE = [
    ("stop_simulation", ["Stop the simulation.", "Halt the run.", "Shut the sim down."],
     ["시뮬레이션 정지해.", "런 중지해줘.", "시뮬레이션 멈춰."]),
    ("pause_simulation", ["Pause the run.", "Freeze the simulation.", "Hold the run."],
     ["일시정지해.", "런 잠깐 멈춰.", "시뮬레이션 일시정지."]),
    ("resume_simulation", ["Resume the simulation.", "Continue the run.", "Pick it back up."],
     ["재개해.", "다시 진행해.", "런 이어서 계속해."]),
]
SPEED_EN = ["Set speed to {x}x.", "Change the speed to {x}x.", "Bump the speed to {x}x."]
SPEED_KO = ["속도를 {x}배로 설정해.", "속도 {x}배로 바꿔.", "{x}배속으로 해줘."]

# Decline banks
MISSING_EN = ["Move the AGV.", "Run the task.", "Set the speed.", "Inspect the station.",
              "Send the AGV over.", "Go run a task.", "Cancel the command."]
MISSING_KO = ["AGV 이동해줘.", "작업 실행해.", "속도 바꿔줘.", "스테이션 검사해.",
              "거기로 보내줘.", "작업 좀 돌려.", "명령 취소해."]
AMBIG_EN = ["Do the thing.", "Take care of it.", "Handle that one over there.",
            "Sort this out.", "Go ahead with that."]
AMBIG_KO = ["그거 해줘.", "저거 처리해줘.", "알아서 해줘.", "저쪽 거 봐줘."]
INVALID_EN = ["Move to station -1.", "Set the speed to 0.", "Set the speed to -2x.",
              "Start with 'five' AGVs.", "Inspect station 999."]
INVALID_KO = ["스테이션 -1로 이동해.", "속도를 0으로 설정해.", "AGV '다섯'대로 시작해.",
              "스테이션 999 검사해.", "속도를 -2배로 해줘."]
NEGATIVE_EN = ["What's the weather today?", "Tell me a joke.", "What can you do?",
               "Hi there.", "Thanks for your help.", "How does the AGV cell work?"]
NEGATIVE_KO = ["오늘 날씨 어때?", "농담 하나 해줘.", "뭐 할 수 있어?", "안녕하세요.",
               "고마워요.", "AGV 셀이 어떻게 동작해?"]
STATE_EN = [("resume_simulation", "Resume."), ("stop_simulation", "That's enough, shut it down."),
            ("pause_simulation", "Hold on, freeze the run."),
            ("resume_simulation", "Pick it back up where we left off.")]
STATE_KO = [("resume_simulation", "다시 진행해."), ("stop_simulation", "이제 멈춰."),
            ("pause_simulation", "잠깐 멈춰둬."), ("resume_simulation", "이어서 계속해.")]

CLARIFY_MSG = "Which station should I target?"
CLARIFY_MSG_KO = "어느 스테이션을 대상으로 할까요?"

STATIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
SPEEDS = [0.5, 1.5, 2.0, 3.0]
AGV_COUNTS = [3, 4, 5, 6, 8]


# Optional trailing fillers multiply the unique surface space so categories that
# share verb templates (disambiguation vs move/run/inspect) don't exhaust the pool
# under the global dedup.
SUFFIX_EN = ["", "", " please.", " now.", " right away.", " when you can.", " thanks."]
SUFFIX_KO = ["", "", " 지금.", " 바로.", " 부탁해.", " 좀.", " 빨리."]


def station_form(n: int, lang: str) -> str:
    forms = STATION_FORMS_KO if lang == "ko" else STATION_FORMS_EN
    return random.choice(forms).format(n=n)


def with_suffix(prompt: str, lang: str) -> str:
    suf = random.choice(SUFFIX_KO if lang == "ko" else SUFFIX_EN)
    if not suf:
        return prompt
    return prompt.rstrip(".") + (suf if suf[0] == " " else " " + suf)


def make(prompt: str, name: str, args: dict, category: str, lang: str) -> dict:
    return {"prompt": prompt, "category": category, "lang": lang,
            "completion": {"name": name, "arguments": args}}


def gen_unique(target: int, factory, dedup: set) -> list:
    """Draw rows from a randomized factory until `target` unique prompts collected."""
    rows, guard = [], 0
    while len(rows) < target and guard < target * 200:
        guard += 1
        row = factory()
        if row["prompt"] in dedup:
            continue
        dedup.add(row["prompt"])
        rows.append(row)
    if len(rows) < target:
        raise RuntimeError(f"factory exhausted: {len(rows)}/{target}")
    return rows


# --- per-category factories -------------------------------------------------
def f_move():
    lang = random.choice(["en", "ko"])
    if random.random() < 0.22:  # named-alias variant
        alias = random.choice([a for a in ALIAS_MAP if (a.isascii()) == (lang == "en")])
        n = ALIAS_MAP[alias]
        tmpl = random.choice(MOVE_KO if lang == "ko" else MOVE_EN)
        return make(with_suffix(tmpl.format(st=alias), lang), "move_to_station", {"station_id": n}, "move_to_station", lang)
    n = random.choice(STATIONS)
    st = station_form(n, lang)
    tmpl = random.choice(MOVE_KO if lang == "ko" else MOVE_EN)
    return make(with_suffix(tmpl.format(st=st), lang), "move_to_station", {"station_id": n}, "move_to_station", lang)


def f_run():
    lang = random.choice(["en", "ko"])
    n = random.choice(STATIONS)
    st = station_form(n, lang)
    tmpl = random.choice(RUN_KO if lang == "ko" else RUN_EN)
    args = {"station_id": n}
    if random.random() < 0.3:
        args["priority"] = "high"
        suffix = " 높은 우선순위로." if lang == "ko" else " With high priority."
        return make(tmpl.format(st=st) + suffix, "run_station_task", args, "run_station_task", lang)
    return make(with_suffix(tmpl.format(st=st), lang), "run_station_task", args, "run_station_task", lang)


def f_inspect():
    lang = random.choice(["en", "ko"])
    n = random.choice(STATIONS)
    st = station_form(n, lang)
    tmpl = random.choice(INSPECT_KO if lang == "ko" else INSPECT_EN)
    return make(with_suffix(tmpl.format(st=st), lang), "inspect_station", {"station_id": n}, "inspect_station", lang)


def f_disambig():
    """SFT target: same station, verb selects the tool."""
    lang = random.choice(["en", "ko"])
    n = random.choice(STATIONS)
    st = station_form(n, lang)
    kind = random.choice(["move", "run", "inspect"])
    if kind == "move":
        tmpl = random.choice(MOVE_KO if lang == "ko" else MOVE_EN); tool = "move_to_station"
    elif kind == "run":
        tmpl = random.choice(RUN_KO if lang == "ko" else RUN_EN); tool = "run_station_task"
    else:
        tmpl = random.choice(INSPECT_KO if lang == "ko" else INSPECT_EN); tool = "inspect_station"
    return make(with_suffix(tmpl.format(st=st), lang), tool, {"station_id": n}, "disambiguation", lang)


def f_kpi():
    """SFT target: start_simulation with nested acceptance[]."""
    lang = random.choice(["en", "ko"])
    n = random.choice(AGV_COUNTS)
    thr = random.choice([60, 65, 70, 75, 80])
    wait = random.choice([10, 12, 15])
    combo = random.choice(["all", "collision", "throughput", "thr_wait"])
    acc = []
    if combo in ("all", "throughput", "thr_wait"):
        acc.append({"metric": "throughput", "comparator": ">=", "threshold": thr})
    if combo in ("all", "thr_wait"):
        acc.append({"metric": "avg_wait_sec", "comparator": "<=", "threshold": wait})
    if combo in ("all", "collision"):
        acc.append({"metric": "collision_count", "comparator": "==", "threshold": 0})
    if lang == "ko":
        parts = []
        if any(a["metric"] == "throughput" for a in acc): parts.append(f"처리량 시간당 {thr} 이상")
        if any(a["metric"] == "avg_wait_sec" for a in acc): parts.append(f"평균 대기 {wait}초 이하")
        if any(a["metric"] == "collision_count" for a in acc): parts.append("충돌 0건")
        prompt = f"{', '.join(parts)}이면 통과로 AGV {n}대 돌려줘."
    else:
        parts = []
        if any(a["metric"] == "throughput" for a in acc): parts.append(f"throughput is at least {thr} per hour")
        if any(a["metric"] == "avg_wait_sec" for a in acc): parts.append(f"average wait is under {wait} seconds")
        if any(a["metric"] == "collision_count" for a in acc): parts.append("collisions are zero")
        prompt = f"Start with {n} AGVs and accept only if {', and '.join(parts)}."
    return make(prompt, "start_simulation", {"agv_count": n, "acceptance": acc}, "kpi_acceptance", lang)


def f_lifecycle():
    lang = random.choice(["en", "ko"])
    pick = random.random()
    if pick < 0.34:  # start
        n = random.choice(AGV_COUNTS)
        tmpl = random.choice(START_KO if lang == "ko" else START_EN)
        return make(tmpl.format(n=n), "start_simulation", {"agv_count": n}, "sim_lifecycle", lang)
    if pick < 0.6:  # speed
        x = random.choice(SPEEDS)
        tmpl = random.choice(SPEED_KO if lang == "ko" else SPEED_EN)
        xs = str(int(x)) if x == int(x) else str(x)
        return make(tmpl.format(x=xs), "set_sim_speed", {"speed_multiplier": x}, "sim_lifecycle", lang)
    tool, en, ko = random.choice(SIMPLE_LIFECYCLE)
    tmpl = random.choice(ko if lang == "ko" else en)
    return make(tmpl, tool, {}, "sim_lifecycle", lang)


def f_start_speed():
    """SFT target gap: start_simulation carrying BOTH agv_count and speed_multiplier
    (the compound 'start at Nx with M AGVs' pairing; ~25% also attach acceptance[])."""
    lang = random.choice(["en", "ko"])
    n = random.choice(AGV_COUNTS)
    x = random.choice(START_SPEEDS)
    xs = str(int(x)) if x == int(x) else str(x)
    if random.random() < 0.25:  # compound + nested acceptance[]
        thr = random.choice([60, 65, 70, 75, 80])
        acc = [{"metric": "throughput", "comparator": ">=", "threshold": thr}]
        if random.random() < 0.5:
            acc.append({"metric": "collision_count", "comparator": "==", "threshold": 0})
        if lang == "ko":
            parts = [f"처리량 시간당 {thr} 이상"]
            if len(acc) > 1: parts.append("충돌 0건")
            goal = ", ".join(parts)
            tmpl = random.choice(START_SPEED_ACC_KO)
        else:
            parts = [f"throughput is at least {thr} per hour"]
            if len(acc) > 1: parts.append("collisions are zero")
            goal = " and ".join(parts)
            tmpl = random.choice(START_SPEED_ACC_EN)
        prompt = tmpl.format(x=xs, n=n, goal=goal)
        return make(prompt, "start_simulation",
                    {"agv_count": n, "speed_multiplier": x, "acceptance": acc},
                    "start_with_speed", lang)
    tmpl = random.choice(START_SPEED_KO if lang == "ko" else START_SPEED_EN)
    return make(with_suffix(tmpl.format(x=xs, n=n), lang), "start_simulation",
                {"agv_count": n, "speed_multiplier": x}, "start_with_speed", lang)


def f_acc_metrics():
    """SFT target gap: start_simulation acceptance[] on the under-covered metrics
    (bottleneck_rate %, uptime_ratio, active_agvs). Single-run verifiable goals — NOT
    optimization search (no optimize verbs), so they route to the tool router."""
    lang = random.choice(["en", "ko"])
    n = random.choice(AGV_COUNTS)
    metric = random.choice(["bottleneck_rate", "uptime_ratio", "active_agvs"])
    phrase, comp, vals = (ACC_METRIC_KO if lang == "ko" else ACC_METRIC_EN)[metric]
    v = random.choice([x for x in vals if metric != "active_agvs" or x <= n])
    vs = str(int(v)) if float(v) == int(v) else str(v)
    goal = phrase.format(v=vs)
    acc = [{"metric": metric, "comparator": comp, "threshold": float(v)}]
    tmpl = random.choice(ACC_START_KO if lang == "ko" else ACC_START_EN)
    return make(tmpl.format(n=n, goal=goal), "start_simulation",
                {"agv_count": n, "acceptance": acc}, "kpi_acceptance_metrics", lang)


def f_missing():
    lang = random.choice(["en", "ko"])
    src = MISSING_KO + AMBIG_KO if lang == "ko" else MISSING_EN + AMBIG_EN
    prompt = with_suffix(random.choice(src), lang)
    msg = CLARIFY_MSG_KO if lang == "ko" else CLARIFY_MSG
    return make(prompt, "clarify", {"message": msg}, "missing_parameter", lang)


def f_invalid():
    lang = random.choice(["en", "ko"])
    prompt = with_suffix(random.choice(INVALID_KO if lang == "ko" else INVALID_EN), lang)
    msg = "그 값은 유효 범위를 벗어납니다. 올바른 값을 알려주세요." if lang == "ko" \
        else "That value is out of the valid range. Please provide a valid one."
    return make(prompt, "clarify", {"message": msg}, "invalid_parameter", lang)


def f_negative():
    lang = random.choice(["en", "ko"])
    prompt = with_suffix(random.choice(NEGATIVE_KO if lang == "ko" else NEGATIVE_EN), lang)
    return make(prompt, "none", {}, "negative_control", lang)


def f_state():
    lang = random.choice(["en", "ko"])
    tool, prompt = random.choice(STATE_KO if lang == "ko" else STATE_EN)
    return make(with_suffix(prompt, lang), tool, {}, "state_dependent", lang)


FACTORIES = {
    "disambiguation": (f_disambig, 60, 10, 20),
    "kpi_acceptance": (f_kpi, 54, 9, 18),
    "move_to_station": (f_move, 36, 6, 12),
    "run_station_task": (f_run, 30, 5, 10),
    "inspect_station": (f_inspect, 24, 4, 8),
    "sim_lifecycle": (f_lifecycle, 36, 6, 12),
    "missing_parameter": (f_missing, 24, 4, 8),
    "invalid_parameter": (f_invalid, 15, 3, 6),
    "negative_control": (f_negative, 12, 2, 4),
    "state_dependent": (f_state, 9, 1, 2),
    # Appended last so every preceding category draws an identical (seeded) sequence;
    # these only *add* rows without perturbing existing splits.
    "start_with_speed": (f_start_speed, 30, 5, 10),
    "kpi_acceptance_metrics": (f_acc_metrics, 24, 4, 8),
}


def main() -> None:
    train, val, test = [], [], []
    dedup: set[str] = set()  # global dedup => zero prompt overlap across splits
    for cat, (factory, n_tr, n_va, n_te) in FACTORIES.items():
        rows = gen_unique(n_tr + n_va + n_te, factory, dedup)
        random.shuffle(rows)
        train += rows[:n_tr]
        val += rows[n_tr:n_tr + n_va]
        test += rows[n_tr + n_va:]
    random.shuffle(train); random.shuffle(val); random.shuffle(test)

    for name, split in [("train", train), ("val", val), ("test", test)]:
        path = OUT_DIR / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in split:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"wrote {path.name}: {len(split)} rows")

    (OUT_DIR / "alias_map.json").write_text(
        json.dumps(ALIAS_MAP, ensure_ascii=False, indent=2), encoding="utf-8")

    # invariants
    all_prompts = [r["prompt"] for r in train + val + test]
    assert len(all_prompts) == len(set(all_prompts)), "prompt overlap across splits!"
    print(f"TOTAL {len(all_prompts)} | unique {len(set(all_prompts))}")
    print("train by category:", dict(Counter(r["category"] for r in train)))


if __name__ == "__main__":
    main()
