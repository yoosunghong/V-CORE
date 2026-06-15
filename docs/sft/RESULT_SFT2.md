# Phase 3 / SFT-2 — LoRA Training Result

> **Status:** ✅ COMPLETE (2026-06-11) · Trained on host GPU (RTX 4060 Ti, 8 GB).
> Base = production `Qwen/Qwen3.5-2B` (HF source of Ollama `qwen3.5:2b`). Base weights
> untouched; only a separate LoRA adapter + a merged copy are produced.

## 1. What was produced (all separate artifacts — base model is never modified)

| Artifact | Path | Size | Purpose |
|---|---|---|---|
| LoRA adapter | `data/adapter/` | 43 MB (`adapter_model.safetensors`) | the trained delta (10.9 M params, 0.58 %) |
| Merged fp16 (HF) | `data/merged-fp16/` | 3.76 GB | base⊕adapter for GGUF conversion / HF serving |
| GGUF f16 | `data/vcore-toolrouter-f16.gguf` | 3.78 GB | conversion intermediate |
| **GGUF q4_k_m** | `data/vcore-toolrouter.gguf` | **1.27 GB** | **served on llama.cpp :8080 for SFT-3 parity** |
| Train metrics | `data/adapter/train_metrics.json` | — | loss curve + log history |

## 2. Training config & run

- QLoRA: 4-bit NF4 base + double-quant, LoRA r=16 α=32 dropout=0.05 on
  `q,k,v,o,gate,up,down_proj`; `paged_adamw_8bit`; gradient checkpointing; bf16.
- Prompt style = **frozen minimal prompt** as system, user = command, assistant = label
  JSON; **prompt tokens masked** (loss on the completion JSON only).
- 3 epochs, effective batch 16 (per-device 8 × grad-accum 2), 57 steps, **~6.8 min**.
- Script: `docs/sft/scripts/train_lora.py` (config `data/lora_config.yaml`).

### Loss curve (converged, monotonic)
| epoch | train loss | eval loss |
|---:|---:|---:|
| 0.5 | 0.558 | — |
| 1.0 | 0.046 | 0.0315 |
| 2.0 | 0.006 | 0.0037 |
| 3.0 | 0.0025 | **0.0029** |

## 3. End-to-end smoke test (q4_k_m, served, **minimal** prompt)

6/6 held-out prompts routed correctly across categories (move / run / inspect / none /
start_simulation; ko + en), e.g.:
- `Drive the robot to station 4.` → `{"name":"move_to_station","arguments":{"station_id":4}}`
- `Begin the simulation using 6 AGVs.` → `{"name":"start_simulation","arguments":{"agv_count":6}}`
- `Hi there.` → `{"name":"none","arguments":{}}`

Formal 3-way matrix (Base+Full / Base+Minimal / SFT+Minimal) is **SFT-3**
(`scripts/eval_sft.py` over `data/test.jsonl`).

## 4. Environment (host, not Docker) — reproducibility notes

- Dedicated venv `C:/Users/PC/sft-train-venv` (Python 3.13.5) — created so the benchmark
  anaconda env's CPU-only torch is left untouched. torch 2.6.0+cu124, transformers 5.11.0,
  peft 0.19.1, bitsandbytes 0.49.2.
- Serve the SFT model exactly like the base, for SFT-3 parity:
  ```
  Intermediate/llama-build/bin/Release/llama-server.exe \
    -m docs/sft/data/vcore-toolrouter.gguf \
    --host 127.0.0.1 --port 8080 -ngl 99 -c 4096 --jinja --reasoning off --reasoning-budget 0
  ```

## 5. Gotchas hit & fixed (Windows / Python 3.13 / bleeding-edge `qwen35`)

1. **pyarrow×torch DLL load-order segfault.** `transformers.Trainer` lazily imports
   `datasets`→`pyarrow`; loading pyarrow *after* torch/bitsandbytes hard-segfaults (exit 139,
   no traceback). Fix: `import datasets` **before** `import torch` in `train_lora.py`.
2. **`datasets` not usable for the dataset itself** (same segfault) — the trainer uses a plain
   `list[dict]` with a custom padding collator instead.
3. **GGUF convert↔load mismatch for the new `qwen35` (Gated-DeltaNet) arch** at llama.cpp
   pinned commit `715b86a36`. Two issues vs the production blob, both fixed at convert time:
   - `conversion/qwen.py` mapped `dt_bias`→`.dt_proj.bias` → GGUF tensor `blk.N.ssm_dt.bias`,
     but the loader requires `blk.N.ssm_dt`. Temporarily patched to `.dt_proj` (reverted after).
   - default convert wrote `block_count=25` while emitting only 24 blocks (MTP over-count) →
     loader looked for nonexistent `blk.24`. Fix: convert with **`--no-mtp`** (`num_hidden_layers=24`).
   - `llama-quantize` was not in the prior build (only `llama-server`); built the target from
     the existing CUDA build dir. The `C:/tmp/llama.cpp` tree is left unmodified.
4. **(2026-06-15 retrain) Quant precision matters for small new categories — use q5_k_m, not q4_k_m.**
   The SFT-5 retrain added `start_with_speed` (30 rows) + extra acceptance metrics. The adapter,
   merged-fp16, **and the f16 GGUF** all emitted the correct `speed_multiplier`/`bottleneck_rate`, but
   **q4_k_m quantization washed those (smaller, newer) distinctions out** — the q4 model reverted to
   its base prior (`agv_speed_multiplier`/`run_simulation`) and scored `start_with_speed` 0/10. Probe
   the export chain f16→q4 separately when a fine-tuned pattern silently regresses. **q5_k_m** (1.34 GB,
   +0.07 GB over q4) preserves them: eval 98.3%, start_with_speed 10/10. `lora_config.yaml quantize`
   is now `q5_k_m`. The original SFT-2 categories were robust to q4; only the new low-frequency ones
   were fragile.
