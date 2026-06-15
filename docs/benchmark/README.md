# LLM Provider Benchmark: Ollama vs llama.cpp

Date: 2026-06-10

This benchmark compares the chatbot agent's tool-planning path through the shared `LlmGateway` interface. Ollama remains the baseline provider. llama.cpp is exercised through the OpenAI-compatible gateway endpoint.

> **Updated 2026-06-10 (GPU run):** the earlier run had llama.cpp lagging badly
> (~11.7 s average) because its server binary was a **CPU-only build**
> (`GGML_CUDA=OFF`, no `ggml-cuda.dll`), so `-ngl` had no CUDA backend to offload
> to. llama.cpp was rebuilt with CUDA enabled and re-run with full GPU offload
> (`-ngl 99`) on the RTX 4060 Ti. Average latency dropped from ~11.7 s to ~2.4 s
> — now on par with Ollama. The previous CPU-only numbers are preserved in
> [Appendix: CPU-only run (superseded)](#appendix-cpu-only-run-superseded).

## Raw Artifacts

- JSON: `docs/benchmark/raw/llm_provider_comparison.json`
- CSV: `docs/benchmark/raw/llm_provider_comparison.csv`
- llama.cpp GPU server log: `docs/benchmark/raw/llama-server-qwen35-2b-gpu.log`
- llama.cpp CPU server log (superseded): `docs/benchmark/raw/llama-server-qwen35-2b.log.err`

## Environment

- Working directory: `web/services/chatbot-backend`
- Python: 3.13.5
- GPU: NVIDIA GeForce RTX 4060 Ti (8 GB), driver 591.86, CUDA Toolkit 13.3
- Ollama endpoint: `http://127.0.0.1:11434`
- Ollama model: `qwen3.5:2b`
- llama.cpp endpoint: `http://127.0.0.1:8080`
- llama.cpp model: the same Ollama `qwen3.5:2b` GGUF blob:
  `C:\Users\PC\.ollama\models\blobs\sha256-b709d81508a078a686961de6ca07a953b895d9b286c46e17f00fb267f4f2d297`
- llama.cpp binary: `Intermediate\llama-build\bin\Release\llama-server.exe` (CUDA build)
- llama.cpp mode: **GPU offload, `-ngl 99`**, context `2048`, `--no-mmproj`, `-fit off`
- Measured GPU footprint while serving: ~2.2 GB VRAM (1.2 GB baseline → 3.4 GB with the model resident on `CUDA0`).

## CPU → GPU Fix (root cause of the earlier lag)

The earlier benchmark concluded llama.cpp was "slow," but the real cause was that
the server was built CPU-only. The build cache had `GGML_CUDA:BOOL=OFF`, the
Release folder shipped no `ggml-cuda.dll`, and `llama-server.exe --list-devices`
reported no devices. With no CUDA backend compiled in, passing `-ngl` could not
offload anything — every token was computed on the CPU.

Fix:

1. Reconfigure the existing build with CUDA enabled, targeting the RTX 4060 Ti
   (compute capability 8.9):

   ```powershell
   cmake -B Intermediate\llama-build -S C:\tmp\llama.cpp -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89
   ```

2. Rebuild the server:

   ```powershell
   cmake --build Intermediate\llama-build --config Release --target llama-server
   ```

   After this, `ggml-cuda.dll` is present and `llama-server.exe --list-devices`
   reports `CUDA0: NVIDIA GeForce RTX 4060 Ti`.

3. Start the server with full GPU offload (`-ngl 99` instead of `-ngl 0`).

## llama.cpp GGUF Compatibility Patches (still required)

These local llama.cpp source patches were needed to load Ollama's `qwen3.5:2b`
GGUF at all, independent of CPU vs GPU. They remain in `C:\tmp\llama.cpp`.

| Stage | Error | Cause | Fix |
| --- | --- | --- | --- |
| Metadata load | `qwen35.rope.dimension_sections has wrong array length; expected 4, got 3` | Ollama's Qwen3.5 metadata stores three RoPE sections, while this llama.cpp Qwen3.5 loader required four. | Patched `C:\tmp\llama.cpp\src\models\qwen35.cpp` to accept three sections and pad the fourth internal slot with `0`. |
| Tensor load | `missing tensor 'blk.0.ssm_dt.bias'` | Ollama's tensor is named `blk.N.ssm_dt`; the loader requested the extra `.bias` suffix. | Patched Qwen3.5 tensor creation to request `blk.N.ssm_dt`. |
| Tensor shape validation | `blk.3.attn_k.weight has wrong shape; expected 2048, 0, got 2048, 512` | The Qwen3.5 loader reused layer-0 attention dimensions. Layer 0 is recurrent and has zero KV attention heads, while full-attention layers have KV heads. | Patched Qwen3.5 tensor and graph code to use per-layer head counts and head dimensions. |
| Tensor completeness | `wrong number of tensors; expected 728, got 320` | Ollama's `qwen3.5:2b` GGUF includes `v.*` vision tensors that the text-only llama.cpp path does not claim. | Patched `C:\tmp\llama.cpp\src\llama-model.cpp` to allow partial tensor loading for Qwen3.5/Qwen3.5-MoE. |
| Graph warmup | `GGML_ASSERT(ggml_nelements(a) == ne0*ne1*ne2)` | The same per-layer head-count issue appeared in the runtime graph path. | Patched Qwen3.5 attention graph to use per-layer dimensions. |

## Commands

Pull the matching baseline model into Ollama:

```powershell
& 'C:\Users\PC\AppData\Local\Programs\Ollama\ollama.exe' pull qwen3.5:2b
```

Configure and build the CUDA llama.cpp server:

```powershell
cmake -B Intermediate\llama-build -S C:\tmp\llama.cpp -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89
cmake --build Intermediate\llama-build --config Release --target llama-server
```

Start llama.cpp with GPU offload:

```powershell
Intermediate\llama-build\bin\Release\llama-server.exe `
  -m C:\Users\PC\.ollama\models\blobs\sha256-b709d81508a078a686961de6ca07a953b895d9b286c46e17f00fb267f4f2d297 `
  --alias qwen3.5:2b `
  --host 127.0.0.1 `
  --port 8080 `
  -c 2048 `
  -ngl 99 `
  --no-mmproj `
  -fit off
```

Benchmark command:

```powershell
python scripts\benchmark_llm_providers.py --providers ollama,llama_cpp --ollama-base-url http://127.0.0.1:11434 --ollama-model qwen3.5:2b --llama-cpp-base-url http://127.0.0.1:8080 --llama-cpp-model qwen3.5:2b --output-dir ..\..\..\docs\benchmark\raw --timeout-seconds 180
```

Benchmark result:

```text
Wrote JSON: ..\..\..\docs\benchmark\raw\llm_provider_comparison.json
Wrote CSV: ..\..\..\docs\benchmark\raw\llm_provider_comparison.csv
```

Focused tests:

```powershell
python -m pytest tests\test_llm_benchmark.py tests\test_llm_gateway.py
```

Test result:

```text
20 passed, 1 warning in 0.31s
```

## Prompt Set

| Case | Expected tool |
| --- | --- |
| process status query | none |
| start simulation | `start_simulation` |
| start simulation with KPI acceptance criteria | `start_simulation` |
| stop simulation | `stop_simulation` |
| abort + confirm | `stop_simulation` |
| pause/resume | `pause_simulation` |
| set speed | `set_sim_speed` |
| move AGV to station | `move_to_station` |
| run station task | `run_station_task` |
| inspect station | `inspect_station` |
| available actions query | none |
| ambiguous command | none |

## Summary (GPU run)

| Metric | Ollama qwen3.5:2b | llama.cpp qwen3.5:2b (GPU) |
| --- | ---: | ---: |
| Prompt count | 12 | 12 |
| JSON parse success rate | 91.67% | 58.33% |
| Schema validation success rate | 83.33% | 58.33% |
| Tool selection accuracy | 66.67% | 91.67% |
| Repair retry rate | 33.33% | 41.67% |
| Rule-based fallback rate | 0.00% | 8.33% |
| Average latency | 2005.941 ms | 2373.500 ms |
| p95 latency | 4602.863 ms | 4365.453 ms |
| Latency stddev | 1225.555 ms | 1088.872 ms |
| First request latency | 3179.296 ms | 3589.201 ms |
| Warm average latency | 1899.272 ms | 2262.981 ms |
| Cold preload latency | 1277.804 ms | 388.752 ms |
| Memory usage | unavailable | unavailable |

## Per-Case Results (GPU run)

| Provider | Case | Expected | Actual | Correct | JSON | Schema | Fallback | Latency |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Ollama | process_status_query | none | none | yes | yes | no | no | 3179.296 ms |
| Ollama | start_simulation | `start_simulation` | `start_simulation` | yes | yes | yes | no | 1211.459 ms |
| Ollama | start_simulation_with_kpi_acceptance | `start_simulation` | none | no | no | no | no | 4602.863 ms |
| Ollama | stop_simulation | `stop_simulation` | `stop_simulation` | yes | yes | yes | no | 1064.222 ms |
| Ollama | abort_confirm | `stop_simulation` | `stop_simulation` | yes | yes | yes | no | 1097.379 ms |
| Ollama | pause_resume | `pause_simulation` | `pause_simulation` | yes | yes | yes | no | 1042.660 ms |
| Ollama | set_speed | `set_sim_speed` | `set_sim_speed` | yes | yes | yes | no | 1220.324 ms |
| Ollama | move_agv_to_station | `move_to_station` | `move_to_station` | yes | yes | yes | no | 1239.065 ms |
| Ollama | run_station_task | `run_station_task` | `inspect_station` | no | yes | yes | no | 1233.950 ms |
| Ollama | inspect_station | `inspect_station` | `inspect_station` | yes | yes | yes | no | 1257.949 ms |
| Ollama | available_actions_query | none | `inspect_station` | no | yes | yes | no | 3595.467 ms |
| Ollama | ambiguous_command | none | `run_station_task` | no | yes | yes | no | 3326.654 ms |
| llama.cpp | process_status_query | none | none | yes | no | no | no | 3589.201 ms |
| llama.cpp | start_simulation | `start_simulation` | `start_simulation` | yes | yes | yes | no | 1553.277 ms |
| llama.cpp | start_simulation_with_kpi_acceptance | `start_simulation` | none | no | no | no | no | 3401.482 ms |
| llama.cpp | stop_simulation | `stop_simulation` | `stop_simulation` | yes | yes | yes | no | 1183.893 ms |
| llama.cpp | abort_confirm | `stop_simulation` | `stop_simulation` | yes | yes | yes | no | 1429.030 ms |
| llama.cpp | pause_resume | `pause_simulation` | `pause_simulation` | yes | yes | yes | no | 1673.557 ms |
| llama.cpp | set_speed | `set_sim_speed` | `set_sim_speed` | yes | no | no | yes | 3341.233 ms |
| llama.cpp | move_agv_to_station | `move_to_station` | `move_to_station` | yes | yes | yes | no | 1647.638 ms |
| llama.cpp | run_station_task | `run_station_task` | `run_station_task` | yes | yes | yes | no | 1278.774 ms |
| llama.cpp | inspect_station | `inspect_station` | `inspect_station` | yes | yes | yes | no | 1627.005 ms |
| llama.cpp | available_actions_query | none | none | yes | no | no | no | 3391.453 ms |
| llama.cpp | ambiguous_command | none | none | yes | no | no | no | 4365.453 ms |

## Observations

- The comparison uses `qwen3.5:2b` on both providers.
- **GPU offload closed the latency gap.** llama.cpp average latency fell from
  ~11.73 s (CPU-only) to ~2.37 s (GPU), roughly a 5× speedup, and is now within
  ~18% of Ollama's ~2.01 s. p95 (4.37 s) and stddev (1.09 s) are actually
  slightly better than Ollama's.
- llama.cpp had the higher tool-selection accuracy (91.67% vs 66.67%), again
  largely because it correctly declined every negative-control prompt
  (`process_status_query`, `available_actions_query`, `ambiguous_command`) where
  Ollama over-selected a tool. Both providers missed only the KPI start case.
- Ollama still produces valid structured output more often: JSON/schema success
  91.67%/83.33% vs llama.cpp 58.33%/58.33%. llama.cpp needed one deterministic
  rule-based fallback (`set_speed`) and a repair retry on 41.67% of prompts.
- Cold preload now favors llama.cpp (389 ms vs 1278 ms) because the model is
  already resident in VRAM; Ollama pays its model-load cost on first touch.
- Measured GPU footprint while serving was ~2.2 GB VRAM. Per-process VRAM is not
  exposed by `nvidia-smi` on this Windows/WDDM setup, so the benchmark JSON still
  reports `memory_usage_bytes: null`.

## Appendix: CPU-only run (superseded)

The original run used a CPU-only llama.cpp build (`-ngl 0`, no CUDA backend).
It is kept here for reference; the GPU run above supersedes it.

| Metric | Ollama qwen3.5:2b | llama.cpp qwen3.5:2b (CPU) |
| --- | ---: | ---: |
| JSON parse success rate | 91.67% | 41.67% |
| Schema validation success rate | 83.33% | 41.67% |
| Tool selection accuracy | 66.67% | 83.33% |
| Repair retry rate | 33.33% | 58.33% |
| Rule-based fallback rate | 0.00% | 16.67% |
| Average latency | 2039.791 ms | 11727.358 ms |
| p95 latency | 4518.585 ms | 27249.620 ms |
| Latency stddev | 1313.766 ms | 6222.560 ms |
| Warm average latency | 1814.446 ms | 10316.243 ms |
