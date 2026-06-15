"""Evaluate an integrated path/action LoRA checkpoint with Transformers/PEFT.

This is a fast experiment checkpoint scorer before doing the slower
merge -> GGUF -> quantize path.

Example:
    C:/Users/PC/sft-train-venv/Scripts/python.exe docs/sft/integrated/scripts/eval_path_action_hf.py \
      --adapter docs/sft/integrated/data/checkpoints/checkpoint-32 --split test
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import platform as _platform

_platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(OSError("wmi probe disabled"))

import datasets  # noqa: F401,E402
import torch  # noqa: E402
from peft import PeftModel  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docs" / "sft" / "integrated" / "scripts"))

from eval_path_action import normalize, parse_json, score  # noqa: E402

DATA = ROOT / "docs" / "sft" / "integrated" / "data"
PROMPT = ROOT / "docs" / "sft" / "integrated" / "prompts" / "path_action_system.txt"


def load_rows(split: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (DATA / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]


def generate(tokenizer, model, system: str, user: str, max_new_tokens: int) -> str:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )
    inputs = {key: value.to(model.device) for key, value in inputs.items()}
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    new_tokens = out[0][inputs["input_ids"].shape[-1] :]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def pct(n: int, d: int) -> float:
    return n / d if d else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--base", default="Qwen/Qwen3.5-2B")
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--out", default=None)
    parser.add_argument("--max-new-tokens", type=int, default=160)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this evaluator.")

    tokenizer = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    base = AutoModelForCausalLM.from_pretrained(
        args.base,
        quantization_config=bnb,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base, str(ROOT / args.adapter)).eval()
    system = PROMPT.read_text(encoding="utf-8").strip()
    rows = load_rows(args.split)

    counts = Counter()
    by_category: dict[str, Counter] = defaultdict(Counter)
    results = []
    for index, item in enumerate(rows, start=1):
        raw = generate(tokenizer, model, system, item["prompt"], args.max_new_tokens)
        pred = normalize(parse_json(raw))
        metrics = score(item["completion"], pred)
        for key, ok in metrics.items():
            counts[key] += int(ok)
            by_category[item["category"]][key] += int(ok)
        by_category[item["category"]]["n"] += 1
        results.append({**item, "prediction": pred, "raw": raw, **metrics})
        if index % 20 == 0:
            print(f"{index}/{len(rows)} full={pct(counts['full_ok'], index):.1%}")

    total = len(rows)
    summary = {
        "adapter": args.adapter,
        "base": args.base,
        "split": args.split,
        "n": total,
        "route_accuracy": pct(counts["route_ok"], total),
        "action_accuracy": pct(counts["action_ok"], total),
        "argument_accuracy": pct(counts["arg_ok"], total),
        "full_decision_accuracy": pct(counts["full_ok"], total),
        "false_positive_action_rate": pct(counts["false_positive_action"], total),
        "by_category": {
            cat: {
                "n": c["n"],
                "route_accuracy": pct(c["route_ok"], c["n"]),
                "full_decision_accuracy": pct(c["full_ok"], c["n"]),
                "false_positive_action_rate": pct(c["false_positive_action"], c["n"]),
            }
            for cat, c in sorted(by_category.items())
        },
        "results": results,
    }
    print(
        f"ADAPTER={args.adapter} split={args.split} n={total} "
        f"route={summary['route_accuracy']:.1%} "
        f"full={summary['full_decision_accuracy']:.1%} "
        f"fp_action={summary['false_positive_action_rate']:.1%}"
    )
    for cat, item in summary["by_category"].items():
        print(f"  {cat:22} {item['full_decision_accuracy']:.0%} ({item['n']})")

    out = Path(args.out) if args.out else DATA / f"eval_hf_{Path(args.adapter).name}_{args.split}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
