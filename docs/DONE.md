# DONE.md — VCORE Agentic-AI Enhancement (completed features)

> Summary of features completed under the Agentic-AI Enhancement plan. Updated after each task.
> For pending work see [PLAN.md](PLAN.md).
>
> **Prior phases (Phase 1–10):** the UE5 AGV simulation, LangGraph multi-agent migration, real-time
> telemetry, and the LLM SFT / quantization / serving work are complete and archived in
> [legacy/DONE.md](legacy/DONE.md). They are the foundation this track builds on — notably the
> multi-agent orchestration, model training/quantization/serving optimization, and eval harness that
> are already in place.

---

## Foundation already in place (carried from legacy)

Relevant existing capabilities this plan extends rather than rebuilds:

- **Multi-agent orchestration** — LangGraph state machine with classify → plan → robot_command /
  optimize / compare / report / general_chat nodes; a goal-seeking optimization loop.
- **Model training & serving optimization** — LoRA SFT of `qwen3.5:2b` for tool routing, GGUF
  quantization, llama.cpp CUDA serving, reasoning-off lever, adapter-toggle single-model serving.
- **Evals** — `benchmark_v2`, SFT eval harness, ~101 pytest tests, KPI-acceptance/disambiguation metrics.
- **RAG scaffold (dead)** — Qdrant provisioned in `web/docker-compose.yml` +
  `web/infra/vector-db/init/collections.json`; `build_qdrant_seed.py` emits placeholder vectors.
  PA in [PLAN.md](PLAN.md) makes this live.

---

## PA — Real RAG

### PA.0 — Spec & corpus (2026-06-19)
- **Spec doc** [docs/spec_rag.md](docs/spec_rag.md): retrieval architecture, two knowledge sources
  (authored docs + auto-ingested run/KPI history), document schema, embedding/vector-store choice
  (bge-m3 or nomic via local Ollama; Qdrant Cosine), hexagonal wiring (`KnowledgeGateway` port +
  `QdrantKnowledgeGateway`/`NullKnowledgeGateway` adapters), a `retrieve` graph node feeding
  `_report_general_chat` + the report path, config keys, IR/reranker plan, RAG eval metrics
  (recall@k, nDCG, faithfulness), and the demo scenarios it unlocks.
- **Corpus replaced.** The inherited pai_chatbot farm/greenhouse seed
  (`web/services/data-seeder/seeds/rag_documents.jsonl`) was replaced with **14 AGV-domain docs**
  across `sop` / `safety` / `spec` / `playbook` / `handoff`, grounded in the real entities
  (`EStationKind`, `ZoneId`, `CapabilityTags`, KPI set incl. `bottleneck_rate`) and aligned with the
  recorded demos (startup, collision-halt, bottleneck optimization, run comparison).
- **Schema + collection.** Extended the document schema with `tags`/`zone_id`/`capability`; renamed
  the Qdrant collection `farm_operations_ko → vcore_operations_ko` and widened its payload schema
  (`web/infra/vector-db/init/collections.json`). Added `web/services/data-seeder/seeds/docs/` (+README)
  for long-form source files the PA.1 chunker will index.
- **Out of scope / follow-ups:** real embeddings + Qdrant upsert (PA.1 rewrites the still-fake
  `build_qdrant_seed.py`); the legacy farm-domain **Postgres** seed (`seed_demo_data.py`, postgres
  `init/*.sql`) is unrelated to the vector collection and left for the broader domain-rename cleanup.

### PA.1 — Real embeddings + ingestion (2026-06-19, code; live run pending)
- **Real ingest job.** Rewrote `web/services/data-seeder/scripts/build_qdrant_seed.py` from the
  fake-vector stub into a working pipeline: loads `seeds/rag_documents.jsonl` **and** chunks
  `seeds/docs/*.md` (paragraph grouping ~800 chars, `key: value` frontmatter for
  `category/zone_id/capability/tags`), embeds each chunk via Ollama `/api/embeddings`
  (title prepended), ensures the Qdrant collection, and upserts over the REST API. Idempotent
  (UUID5 point ids from `document_id`+chunk index), with `--dry-run` (no network) and `--recreate`.
  Runs from host anaconda python or in-stack via env (`QDRANT_URL`/`OLLAMA_BASE_URL`/`RAG_EMBED_MODEL`/
  `RAG_COLLECTION`).
- **Embedding model = `bge-m3`** (multilingual, strong Korean; 1024-dim). Collection dim updated
  `768 → 1024` in `web/infra/vector-db/init/collections.json`; the `ollama-model` compose service now
  also pulls `RAG_EMBED_MODEL` so the stack is self-provisioning. RAG env keys added to `.env.example`
  (`RAG_ENABLED`/`RAG_COLLECTION`/`RAG_EMBED_MODEL`/`RAG_TOP_K`). `httpx` added as the seeder's one
  dependency (`requirements.txt` + Dockerfile `pip install`).
- **Example source doc** `seeds/docs/runbook_zone2_congestion.md` (Zone 2 혼잡 대응 런북) added — both a
  demo of the "drop a file to upload knowledge" workflow and a chunker test.
- **Engine-agnostic embeddings.** Embedding calls use the **OpenAI-compatible `/v1/embeddings`**
  endpoint (served by both Ollama and llama.cpp) via `EMBED_BASE_URL`, so the serving engine is a
  base-URL change with no code rewrite. **Decision:** the chat/routing LLM stays on **llama.cpp**
  (`adapter_toggle` — per-request LoRA scaling is llama.cpp-only); embeddings run on **Ollama**
  (`bge-m3`), independent and without GPU contention. A deliberate, documented split rather than
  forcing one engine.
- **Verified live (2026-06-19).** Pulled `bge-m3` (1024-dim) to host Ollama, started the Qdrant
  container, ran `build_qdrant_seed.py --recreate`: **16 points upserted** into `vcore_operations_ko`
  (status green, dim 1024, Cosine). Retrieval correct end-to-end — collision query
  ("AGV 충돌이 발생하면 어떻게 대응해?") → `sop_collision_001` ranked **#1 @ 0.719** vs #2 @ 0.601;
  cos(query, relevant doc)=0.903, cos(unrelated docs)=0.397. (An earlier flat-score reading was a
  shell test artifact — a 1024-float vector truncated through a bash variable — not an index issue.)

### PA.2 — Retrieval node in the LangGraph (2026-06-19)
- **`KnowledgeGateway` port** (`application/ports.py`) + two adapters
  (`infrastructure/knowledge_gateway.py`): `QdrantKnowledgeGateway` embeds the query through the
  OpenAI-compatible `/v1/embeddings` endpoint (`EMBED_BASE_URL`, Ollama `bge-m3`), searches the
  `vcore_operations_ko` collection over Qdrant REST, and maps each hit's payload to a new
  `RetrievedChunk` domain model; `NullKnowledgeGateway` returns `[]` so a disabled/down store never
  hard-fails the demo. Adapter errors are swallowed to `[]` (best-effort grounding).
- **Config + container** (`config.py`, `container.py`): `RAG_ENABLED` (default off) selects the
  Null vs Qdrant gateway; `QDRANT_URL`/`RAG_COLLECTION`/`RAG_EMBED_MODEL`/`RAG_TOP_K`/`EMBED_BASE_URL`
  are all env-overridable. The gateway is injected into `ChatOrchestrator`.
- **`retrieve` graph node** (`multi_response_graph.py`): the `general_chat` route now flows
  `classify → retrieve → report_general_chat`. The node calls `ChatOrchestrator._retrieve_knowledge`,
  which retrieves top-k chunks and publishes an `agent.retrieval` `DomainEvent`
  (`{query, hits:[{document_id,title,score}]}`) **only when there are hits** (no event noise when RAG
  is off). Retrieved chunks are threaded into `generate_chat_response`.
- **Report grounding**: `handle_completion_event` builds a KPI-biased retrieval query
  (`_report_retrieval_query` — surfaces collision/bottleneck/throughput concerns) and threads the
  chunks through `ReportAgent.generate_report` → `LlmGateway.generate_report`. `report_user.txt` gained
  a `참고 문서:` block + an inline-citation instruction; `generate_chat_response` injects the same block
  into its system prompt. `format_knowledge_block` renders chunks as numbered, citable text.
- **Verified**: 107 backend tests pass (incl. new `tests/test_rag_retrieval.py` — Null gateway, block
  formatting, knowledge threading into the LLM, and "no `agent.retrieval` event when RAG off"). Live
  adapter check against the running stack: collision query → `sop_collision_001` #1 @ 0.601 over Qdrant.

### PA.3 — IR optimization (2026-06-19)
- **Configurable rerank stage.** `QdrantKnowledgeGateway` now fetches a wider candidate pool
  (`RAG_FETCH_K`, default 10) before returning `RAG_TOP_K`. It supports `RAG_RERANK_MODE=vector`
  (pure Qdrant score), `lexical` (offline-safe token-overlap fusion), and `llm` (OpenAI-compatible
  `/v1/chat/completions` reranker via `RAG_RERANK_BASE_URL`/`RAG_RERANK_MODEL`, with lexical fallback
  on invalid output). Returned chunks preserve both `vector_score` and `rerank_score` for tracing and
  evaluation. `RAG_MIN_SCORE` can suppress weak candidates before prompt injection.
- **PA.3 eval set + runner.** Added `app/benchmarks/rag_cases.py`, `app/benchmarks/rag_eval.py`, and
  `scripts/eval_rag_retrieval.py` for labeled recall@k / nDCG@k measurement over the live Qdrant
  stack. Live run against localhost Qdrant + Ollama `bge-m3`: vector baseline recall@5 **1.0**,
  nDCG@5 **0.884**; tuned lexical rerank recall@5 **1.0**, nDCG@5 **0.884** on the first 6 labeled
  AGV-domain queries. The tuning result keeps embeddings dominant (90%) because English-to-Korean
  queries already rank well semantically and naive lexical fusion can overreact to generic words.
- **Grounding prompt pass.** Knowledge blocks now cite document titles as `[출처: title]`, and both
  report/general-chat prompts include the exact `"not in the knowledge base"` miss behavior when no
  retrieved chunk supports an operational claim.
- **Verified.** Backend suite: `112 passed` with `python -m pytest -q --basetemp .pytest_tmp`.

### PA.4 ??RAG evals / regression (2026-06-19)
- **Regression harness.** Extended `app/benchmarks/rag_cases.py` + `app/benchmarks/rag_eval.py`
  from retrieval-only PA.3 metrics into a PA.4 harness: labeled retrieval recall/nDCG, deterministic
  fixture rankings, and answer-grounding/faithfulness checks for citations, grounded terms,
  hallucinated forbidden terms, and honest `"not in the knowledge base"` abstention.
- **Locked baseline.** Added `docs/benchmark/RAG_PA4_BASELINE.json` with the PA.4 thresholds
  (`retrieval.recall_at_k`, `retrieval.ndcg_at_k`, citation/faithfulness/grounded/abstention rates).
  The live runner `scripts/eval_rag_retrieval.py` now reports both retrieval and answer-grounding
  summaries and can compare against the baseline via `--baseline`.
- **Pytest gate.** `tests/test_rag_eval.py` now gates the deterministic baseline and includes a
  negative ungrounded-answer case, so retrieval or prompting regressions trip the suite even without
  a live Qdrant/LLM stack.
- **Verified.** Backend RAG eval tests pass with
  `python -m pytest tests/test_rag_eval.py -q --basetemp .pytest_tmp`; full backend suite passes
  with `python -m pytest -q --basetemp .pytest_tmp` (`115 passed`).

## PB — GraphRAG + Ontology

### PB — GraphRAG + Ontology (2026-06-19)
- **Ontology spec** [docs/spec_ontology.md](docs/spec_ontology.md): defined the typed AGV-cell graph
  (`Cell`/`Zone`/`Station`/`Capability`/`Run`/`Kpi`) and the multi-hop retrieval path for
  station/zone/capability/KPI questions.
- **Graph construction.** Added `app/domain/ontology.py` with a deterministic `OntologyGraphBuilder`
  that builds from structured station registry data plus saved `SimulationRun.kpis_json`, including
  capability derivation from station type and latest KPI evidence. Added
  `scripts/export_ontology_graph.py` to materialize the projection as JSON for inspection.
- **Hybrid GraphRAG.** Added `HybridGraphKnowledgeGateway`: relational questions route to the graph
  path and return citable `RetrievedChunk` context (`source=ontology_graph`,
  `category=graph_ontology`); free-text SOP/spec questions keep using the PA Qdrant vector path.
  The container wraps Qdrant when `RAG_ENABLED=true` and `GRAPH_RAG_ENABLED=true`.
- **PB evals.** Extended the PA.4 harness with two multi-hop GraphRAG cases and baseline thresholds
  (`graph_retrieval.recall_at_k=1.0`, `graph_retrieval.ndcg_at_k=1.0`). Live eval smoke passes:
  flat retrieval recall@5 `1.0`, nDCG@5 `0.884`; graph retrieval recall/nDCG `1.0`.
- **Verified.** Focused RAG/GraphRAG tests pass (`17 passed`); full backend suite passes
  (`119 passed`). The ontology export job produced the expected cell/zone/station/capability graph.

## PC — Guardrails + Observability

### PC — Guardrails + Observability (2026-06-19)
- **Safety boundary.** Added `SafetyGateway` at the chat boundary: user input and assistant output are HTML/script stripped, control-character cleaned, and PII/secret redacted before storage or response. Prompt-injection and obvious off-domain requests short-circuit before LangGraph with a normal assistant refusal plus a redacted `safety.refused` event.
- **Retrieved-text hardening.** RAG/GraphRAG chunks are now treated as untrusted input before prompt injection: titles/sources/text are sanitized, PII is redacted, and instruction-like retrieved phrases such as "ignore previous instructions" / "system prompt" are replaced with `[retrieved-instruction-redacted]`.
- **Redacted event logs + traces.** `InMemoryEventBus` redacts payloads before storing and fanning out events. `TurnTraceSink` appends an `agent.turn.traced` event to every LangGraph turn with an OTel-shaped local span: route, node path, retrieval hits, estimated input/output tokens, latency, and quality buckets (`low_grounding`, `possible_misroute`).
- **Observability loop.** The first concrete improvement from the new trace/safety pass was the RAG prompt-injection path: before PC, retrieved text could carry hostile instructions and PII into the prompt/log payload; after PC, the trace still records retrieval hit count while the injected chunk is redacted and neutralized before LLM use. This is locked by `tests/test_safety_observability.py`.
- **Verified.** Focused PC tests pass (`3 passed`); full backend suite passes with `python -m pytest -q --basetemp .pytest_tmp` (`122 passed`).

## PD — Real CSP Deployment

### PD — Qdrant Managed Cloud deployment (2026-06-21)

- **CSP decision.** Selected Qdrant Managed Cloud Free Tier for the real cloud component: it moves
  the enterprise knowledge index off-box while retaining UE5, LangGraph, the fine-tuned router, and
  `bge-m3` inference locally. This reuses the production Qdrant REST contract and avoids a paid model
  endpoint for the portfolio workload.
- **Cloud wiring + offline failback.** Added `QDRANT_API_KEY` authentication to backend retrieval and
  corpus ingestion. `QDRANT_FALLBACK_URL` retries the local mirror after a cloud HTTP failure and
  deliberately does not forward the cloud key. Default configuration remains local/offline-safe.
- **Deployment runbook + narrative.** Added [docs/deploy_csp.md](docs/deploy_csp.md) with topology,
  data boundary, current Free Tier constraints, account/seed/verification steps, offline profile,
  and the live-demo portfolio script. Updated the top-level README with the hybrid deployment story.
- **Managed deployment live.** Created and seeded `vcore_operations_ko` on Qdrant Managed Cloud
  (GCP `australia-southeast1`). The sanitized verifier reports green status, 1024-dim Cosine vectors,
  16 points, and `sop_collision_001` ranked first at `0.62117743` for the collision-response query.
  The backend adapter returns that document from cloud-primary and from a forced local failback.
- **Regression verification.** Cloud-auth/failback regression test passes, corpus dry run finds 16
  chunks, and the full backend suite passes (`123 passed`). Credentials remain only in ignored
  `web/.env`; no API key is present in tracked files or verifier output.
- **Live verification gate.** Added `verify_qdrant_deployment.py`, which returns sanitized JSON and a
  nonzero exit code unless the deployed collection is green, 1024-dim Cosine, has at least 16 points,
  and ranks `sop_collision_001` first for the collision-response query. The command passes against
  both the managed deployment and local mirror with all checks true and top score `0.62117743`.
