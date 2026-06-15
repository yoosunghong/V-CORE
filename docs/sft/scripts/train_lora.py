"""Phase 3 / SFT-2 — QLoRA fine-tune for V-CORE Domain Tool Routing.

Trains a LoRA adapter on the deployed production base (`Qwen/Qwen3.5-2B`, HF source
of Ollama `qwen3.5:2b`) so accurate control JSON is produced under the *minimal*
planner prompt. The base weights are never modified — only the adapter is saved
(`docs/sft/data/adapter`). A merged fp16 model is optionally exported for GGUF
conversion (llama.cpp serving parity with the benchmark harness).

Chat format per row: system = frozen MINIMAL prompt, user = row.prompt,
assistant = json.dumps(row.completion). Prompt tokens are masked (-100); loss is
computed on the completion JSON only.

Run (dedicated GPU env):
  python docs/sft/scripts/train_lora.py --config docs/sft/data/lora_config.yaml
Knobs come from the YAML; CLI flags override (--epochs, --batch, --no-merge).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# pandas>=3 calls platform.win32_ver() (a WMI query) at import; on a host whose WMI
# service is slow/wedged this hangs indefinitely with no output. datasets imports pandas,
# so neutralize the WMI probe before that happens — it falls back to the registry path.
import platform as _platform

_platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(OSError("wmi probe disabled"))

# MUST precede torch: on Windows/py3.13 pyarrow's native DLLs segfault if loaded
# after torch/bitsandbytes. transformers.Trainer pulls in datasets→pyarrow lazily,
# so we force the safe load order here. See docs/sft/RESULT_SFT2.md.
import datasets  # noqa: F401  (import-order side effect only)
import torch
import yaml
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)

ROOT = Path(__file__).resolve().parents[3]

MINIMAL_PROMPT = (
    "You are the V-CORE tool planner.\n"
    "Given a user command, select exactly one tool and produce valid JSON arguments.\n"
    "Do not explain. Do not invent missing IDs. If required information is missing,\n"
    "return the clarify tool instead of guessing.\n"
    'Output JSON only: {"name": <tool>, "arguments": {...}}.'
)


def load_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_example(tokenizer, row: dict, max_len: int) -> dict:
    """Tokenize one row; mask the prompt so loss falls only on the completion JSON."""
    completion = json.dumps(row["completion"], ensure_ascii=False)
    prefix_ids = tokenizer.apply_chat_template(
        [{"role": "system", "content": MINIMAL_PROMPT},
         {"role": "user", "content": row["prompt"]}],
        tokenize=True, add_generation_prompt=True, return_dict=False,
    )
    if not isinstance(prefix_ids, list):  # transformers 5.x may return a tensor/BatchEncoding
        prefix_ids = prefix_ids["input_ids"] if hasattr(prefix_ids, "keys") else list(prefix_ids)
    completion_ids = tokenizer(completion, add_special_tokens=False)["input_ids"]
    completion_ids.append(tokenizer.eos_token_id)

    input_ids = (prefix_ids + completion_ids)[:max_len]
    labels = ([-100] * len(prefix_ids) + completion_ids)[:max_len]
    return {"input_ids": input_ids, "labels": labels, "attention_mask": [1] * len(input_ids)}


def collate(batch: list[dict], pad_id: int) -> dict:
    width = max(len(b["input_ids"]) for b in batch)
    out = {"input_ids": [], "labels": [], "attention_mask": []}
    for b in batch:
        pad = width - len(b["input_ids"])
        out["input_ids"].append(b["input_ids"] + [pad_id] * pad)
        out["labels"].append(b["labels"] + [-100] * pad)
        out["attention_mask"].append(b["attention_mask"] + [0] * pad)
    return {k: torch.tensor(v) for k, v in out.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "docs/sft/data/lora_config.yaml"))
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--no-merge", action="store_true", help="skip merged fp16 export")
    a = ap.parse_args()

    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    lora_cfg, tr_cfg, exp = cfg["lora"], cfg["train"], cfg["export"]
    base = cfg["base_model"]
    max_len = tr_cfg["max_seq_len"]
    adapter_dir = ROOT / exp["adapter_dir"]
    merged_dir = adapter_dir.parent / "merged-fp16"

    if not torch.cuda.is_available():
        raise SystemExit("CUDA GPU required for QLoRA; none visible to torch.")
    print(f"GPU: {torch.cuda.get_device_name(0)}  base={base}")

    tokenizer = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base, quantization_config=bnb, torch_dtype=torch.bfloat16,
        device_map={"": 0}, trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=lora_cfg["r"], lora_alpha=lora_cfg["alpha"], lora_dropout=lora_cfg["dropout"],
        target_modules=lora_cfg["target_modules"], bias=lora_cfg["bias"],
        task_type="CAUSAL_LM",
    ))
    model.print_trainable_parameters()
    model.config.use_cache = False

    def to_ds(name: str) -> list[dict]:
        rows = load_rows(ROOT / cfg["data"][name])
        return [build_example(tokenizer, r, max_len) for r in rows]

    train_ds, val_ds = to_ds("train"), to_ds("val")

    args = TrainingArguments(
        output_dir=str(adapter_dir.parent / "checkpoints"),
        num_train_epochs=a.epochs or tr_cfg["epochs"],
        per_device_train_batch_size=a.batch or tr_cfg["per_device_batch_size"],
        per_device_eval_batch_size=a.batch or tr_cfg["per_device_batch_size"],
        gradient_accumulation_steps=tr_cfg["grad_accum"],
        learning_rate=float(tr_cfg["lr"]),
        lr_scheduler_type=tr_cfg["lr_scheduler"],
        warmup_ratio=tr_cfg["warmup_ratio"],
        bf16=tr_cfg["bf16"],
        eval_strategy=tr_cfg["eval_strategy"],
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=10,
        report_to="none",
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
    )

    trainer = Trainer(
        model=model, args=args,
        train_dataset=train_ds, eval_dataset=val_ds,
        data_collator=lambda b: collate(b, tokenizer.pad_token_id),
    )
    trainer.train()

    adapter_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"adapter saved -> {adapter_dir}")

    metrics = trainer.evaluate()
    (adapter_dir / "train_metrics.json").write_text(
        json.dumps({**metrics, "log_history": trainer.state.log_history},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if not a.no_merge:
        print("merging adapter into fp16 base for GGUF export ...")
        del model, trainer
        torch.cuda.empty_cache()
        from peft import PeftModel
        fp16 = AutoModelForCausalLM.from_pretrained(
            base, torch_dtype=torch.float16, device_map="cpu", trust_remote_code=True)
        merged = PeftModel.from_pretrained(fp16, str(adapter_dir)).merge_and_unload()
        merged.save_pretrained(str(merged_dir), safe_serialization=True)
        tokenizer.save_pretrained(str(merged_dir))
        print(f"merged fp16 saved -> {merged_dir}")
        print("Next: convert to GGUF via llama.cpp convert_hf_to_gguf.py, then quantize "
              f"{exp['quantize']} -> {ROOT / exp['merged_gguf']}")


if __name__ == "__main__":
    main()
