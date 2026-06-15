# V-CORE Tool-Routing SFT Dataset (Phase 3 / SFT-1, extended SFT-5)

**Generated:** 2026-06-11 · **Extended:** 2026-06-15 (SFT-5) · **Seed:** 20260611
**Generator:** `docs/sft/scripts/build_sft_dataset.py`
**Validated:** all 531 labels pass production `ToolRouter.validate(check_ranges=True)`
(`docs/sft/scripts/validate_labels.py`).

## Files
| File | Rows | Purpose |
|---|---:|---|
| `train.jsonl` | 354 | LoRA training |
| `val.jsonl` | 59 | early-stop / checkpoint selection |
| `test.jsonl` | 118 | held-out eval (SFT-3/5) — **no prompt overlaps train/val** |
| `alias_map.json` | — | named-area → integer `station_id` map used in prompts |

## Row schema
```json
{"prompt": "<user command>", "category": "<category>", "lang": "ko|en",
 "completion": {"name": "<tool|none|clarify>", "arguments": {...}}}
```
- `completion` is the **exact production parse target** (`{"name","arguments"}`),
  grounded on `web/services/chatbot-backend/app/tools/contracts.py` (9 real tools).
- Decline rows use the production sentinels: `none` (out-of-scope / status / greeting),
  `clarify` (missing required arg / ambiguous / invalid value, with a `message`).

## Split composition (per category)
| Category | Tool target | Train | Val | Test |
|---|---|---:|---:|---:|
| disambiguation | move/run/inspect by verb | 60 | 10 | 20 |
| kpi_acceptance | start_simulation + acceptance[] | 54 | 9 | 18 |
| move_to_station | move_to_station | 36 | 6 | 12 |
| run_station_task | run_station_task | 30 | 5 | 10 |
| inspect_station | inspect_station | 24 | 4 | 8 |
| sim_lifecycle | start/stop/pause/resume/set_sim_speed | 36 | 6 | 12 |
| missing_parameter | clarify | 24 | 4 | 8 |
| invalid_parameter | clarify | 15 | 3 | 6 |
| negative_control | none | 12 | 2 | 4 |
| state_dependent | lifecycle (coherent) | 9 | 1 | 2 |
| start_with_speed *(SFT-5)* | start_simulation + agv_count + speed_multiplier | 30 | 5 | 10 |
| kpi_acceptance_metrics *(SFT-5)* | start_simulation + acceptance[bottleneck_rate/uptime_ratio/active_agvs] | 24 | 4 | 8 |
| **Total** | | **354** | **59** | **118** |

The two SFT-5 categories are appended last in the generator so every prior category draws an
identical seeded sequence — the original 450 rows are reproduced unchanged, only these are added.
`bottleneck_rate` thresholds are on the backend's percent scale (0–100); the rows avoid optimize
verbs so they route to the tool router, not the `optimize_agv_count` node.

## Augmentation
Verb / station-form / courtesy-suffix slot expansion over the v2 templates. Named-area
aliases (loading area→1, shipping area→12, warehouse→10, + ko equivalents) appear in a
fraction of `move_to_station` rows. AGV surface forms vary cosmetically only — current
tools are single-AGV so no AGV id is a label argument.

## Invariants enforced by the generator
1. **Zero prompt overlap** across the three splits (global dedup; asserted at build).
2. Every label validates against the live `ToolRouter` + range checks.
3. Per-category counts exactly match the table above.
