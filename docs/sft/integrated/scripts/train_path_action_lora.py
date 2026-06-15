"""Train the integrated path/action LoRA using the existing SFT trainer.

The original trainer is intentionally left untouched because it belongs to the
tool-router experiment. This wrapper swaps its module-level training prompt and
passes the integrated config.

Run:
    C:/Users/PC/sft-train-venv/Scripts/python.exe docs/sft/integrated/scripts/train_path_action_lora.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docs" / "sft" / "scripts"))

import train_lora  # noqa: E402


def main() -> None:
    prompt = (ROOT / "docs" / "sft" / "integrated" / "prompts" / "path_action_system.txt").read_text(
        encoding="utf-8"
    )
    train_lora.MINIMAL_PROMPT = prompt.strip()
    sys.argv = [
        sys.argv[0],
        "--config",
        str(ROOT / "docs" / "sft" / "integrated" / "data" / "lora_config.yaml"),
        *sys.argv[1:],
    ]
    train_lora.main()


if __name__ == "__main__":
    main()
