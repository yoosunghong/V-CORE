"""Validate every SFT label against the REAL production tool contracts.

Real-tool labels must pass ``ToolRouter.validate(check_ranges=True)``; decline
labels must use a production decline sentinel (``_DECLINE_NAMES`` in the gateway:
none/clarify/...). Run on host anaconda:
    C:/Users/PC/anaconda3/python.exe docs/sft/scripts/validate_labels.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "web" / "services" / "chatbot-backend"
sys.path.insert(0, str(BACKEND))

from app.domain.models import RobotCommandName, ToolCall  # noqa: E402
from app.tools.router import ToolRouter  # noqa: E402

DECLINE = {"none", "no_tool", "no-tool", "noop", "null", "clarify", "clarification"}
DATA = Path(__file__).resolve().parents[1] / "data"
router = ToolRouter()


def main() -> None:
    total = ok = 0
    errors: list[str] = []
    for split in ("train", "val", "test"):
        for i, line in enumerate((DATA / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()):
            total += 1
            row = json.loads(line)
            comp = row["completion"]
            name, args = comp["name"], comp["arguments"]
            if name in DECLINE:
                ok += 1
                continue
            try:
                tc = ToolCall(name=RobotCommandName(name), arguments=dict(args))
                router.validate(tc, check_ranges=True)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{split}#{i} {name} {args} -> {exc}")
    print(f"validated {ok}/{total} labels")
    if errors:
        print("FAILURES:")
        for e in errors[:30]:
            print(" ", e)
        sys.exit(1)
    print("ALL LABELS VALID against production ToolRouter")


if __name__ == "__main__":
    main()
