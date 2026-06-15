"""Resume the integrated path/action LoRA run from a Trainer checkpoint.

The shared trainer does not expose resume_from_checkpoint on its CLI, so this
wrapper replaces the imported Trainer class with a tiny subclass that resumes
from the integrated checkpoint path.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docs" / "sft" / "scripts"))

import train_lora  # noqa: E402


class ResumeTrainer(train_lora.Trainer):
    def train(self, *args, **kwargs):  # noqa: ANN001, ANN201
        kwargs.setdefault(
            "resume_from_checkpoint",
            str(ROOT / "docs" / "sft" / "integrated" / "data" / "checkpoints" / "checkpoint-32"),
        )
        return super().train(*args, **kwargs)


def main() -> None:
    prompt = (ROOT / "docs" / "sft" / "integrated" / "prompts" / "path_action_system.txt").read_text(
        encoding="utf-8"
    )
    train_lora.MINIMAL_PROMPT = prompt.strip()
    train_lora.Trainer = ResumeTrainer
    sys.argv = [
        sys.argv[0],
        "--config",
        str(ROOT / "docs" / "sft" / "integrated" / "data" / "lora_config.yaml"),
        *sys.argv[1:],
    ]
    train_lora.main()


if __name__ == "__main__":
    main()
