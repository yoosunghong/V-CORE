# PLAN.md — VCORE Agentic-AI Enhancement Plan

> **Rule:** Read this before every task. Mark tasks `[x]` immediately upon completion.
> Completed work is summarized in [DONE.md](DONE.md).
> **Current focus:** Close the Agentic-AI capability gaps — Knowledge Store + RAG/GraphRAG,
> Guardrails/Observability, and a real CSP deployment.
> **Prior phases (Phase 1–10: UE5 sim, LangGraph migration, telemetry, SFT/serving):** archived in
> [legacy/PLAN.md](legacy/PLAN.md) + [legacy/DONE.md](legacy/DONE.md). Those remain the foundation;
> this plan builds on them.

---

## Why this plan

The platform is already strong on **multi-agent orchestration**, **model training/quantization/serving
optimization** (LoRA SFT of `qwen3.5:2b`, GGUF, llama.cpp CUDA, adapter-toggle), and **evals**. The
weak cluster is **Enterprise Knowledge Store + RAG (incl. Advanced/GraphRAG) + IR**, plus
**Guardrails/PII**, **Observability**, **Ontology-based services**, and a credible **CSP** story.

One well-built feature — **ontology-grounded GraphRAG over the AGV/Station/KPI domain** — closes the
biggest cluster at once and reuses the existing (currently dead) Qdrant scaffold. The remaining tracks
are cheap add-ons that round out Safety/Observability and Cloud.

> **Note on the legacy P6 UE5 refactor:** good engineering hygiene, but it moves no capability needle
> for this track. It stays parked in [legacy/PLAN.md](legacy/PLAN.md) and is **not** a prerequisite here.

---

## Critical Path

`PA (real RAG) → PB (GraphRAG + ontology) → PC (guardrails + observability) → PD (CSP deployment)`.
PA + PB alone convert four currently-missing capabilities to working. PC and PD can proceed in
parallel once PA lands.

---

## PA — Real RAG (Enterprise Knowledge Store + RAG + IR)

> **Goal:** Replace the fake-vector scaffold with a working retrieval pipeline that grounds agent
> answers in a real corpus. Closes Knowledge Store + RAG + IR + strengthens Context Engineering.
>
> **Current state (from legacy):** Qdrant is provisioned in `web/docker-compose.yml` +
> `web/infra/vector-db/init/collections.json`, and `web/services/data-seeder/scripts/build_qdrant_seed.py`
> emits **fake SHA-256 hash vectors** from `seeds/rag_documents.jsonl`. The backend app imports **zero**
> embedding/retrieval code — RAG is dead. This track makes it live.

### PA.0 — Spec & corpus (do first; gates the rest) ✅ done 2026-06-19 → [docs/spec_rag.md](docs/spec_rag.md)
- [x] Write `docs/spec_rag.md` — retrieval architecture, corpus schema, embedding model choice,
      chunking, the LangGraph wiring points, and eval metrics.
- [x] Define the **domain corpus** + metadata schema; replaced the stale farm/greenhouse seed with
      14 AGV-domain docs and renamed the Qdrant collection `farm_operations_ko → vcore_operations_ko`.
      Added `seeds/docs/` for long source files. (Run/KPI-history ingestion stays in PA.2.)

### PA.1 — Real embeddings + ingestion ✅ code done 2026-06-19 (live run pending stack)
- [x] Swapped `deterministic_vector()` for real Ollama embeddings (`bge-m3`, configurable via
      `RAG_EMBED_MODEL`); collection dim set to 1024, self-pulled by the `ollama-model` compose step.
- [x] Rewrote `build_qdrant_seed.py` into a real ingest job: loads `rag_documents.jsonl` + chunks
      `seeds/docs/*.md` (frontmatter-aware), embeds (title-prepended), ensures the Qdrant collection,
      and upserts with metadata payloads. Idempotent (UUID5 point ids from `document_id`+chunk),
      `--dry-run`/`--recreate` flags, runs from host anaconda python or in-stack. httpx dep added.
- [x] **Verified live 2026-06-19:** `bge-m3` (1024-dim) on host Ollama via OpenAI-compatible
      `/v1/embeddings` (engine-agnostic — same call works on llama.cpp), Qdrant container up. 16 points
      upserted into `vcore_operations_ko` (status green). Retrieval correct: collision query →
      `sop_collision_001` #1 @ 0.719 vs #2 @ 0.601; cos(query, relevant)=0.903, cos across unrelated
      docs=0.397.

### PA.2 — Retrieval node in the LangGraph ✅ done 2026-06-19
- [x] Add a `KnowledgeGateway` (hexagonal port + Qdrant adapter) in `chatbot-backend` alongside the
      existing gateways. Validate at the boundary only.
- [x] Add a `retrieve` graph node that grounds `report` and `general_chat`: query → embed → top-k
      (with metadata filter) → inject as context. Emit a `agent.retrieval` event for observability.
- [x] Ground the `ReportAgent` so a KPI verdict cites the relevant SOP/spec ("throughput dropped;
      SOP-12 says reduce Zone-2 AGV count").

### PA.3 — IR optimization
- [x] Add a reranker (cross-encoder or LLM-rerank) over the top-k; measure nDCG/recall on a small
      labeled query set. Tune chunk size + k.
- [x] Prompt-engineering pass: citation format, grounded-vs-ungrounded guard ("say 'not in the
      knowledge base' rather than hallucinate").

### PA.4 — RAG evals (regression)
- [x] Add a RAG eval harness (retrieval recall + answer-grounding/faithfulness) next to the existing
      `benchmark_v2` / SFT eval. Lock a baseline; wire into the pytest suite.

---

## PB — GraphRAG + Ontology (Advanced RAG + Ontology-based service)

> **Goal:** Formalize the domain as an ontology and do multi-hop retrieval flat RAG can't. Upgrades
> RAG to "Advanced/GraphRAG" and closes the Ontology-based-service capability.
>
> Entities already exist in the domain: `Station`–`AGV`–`Zone`–`Capability`–`Scenario`–`Run/KPI`
> (`EStationKind`/`CapabilityTags`/`ZoneId` in UE5; `Station`/`ProcessTelemetry` in the backend).

- [ ] Define the ontology (RDF/OWL or a typed `networkx` graph) for the AGV cell domain; document in
      `docs/spec_ontology.md`. Build it from existing structured data (station registry +
      run/KPI history), not hand-authored prose.
- [ ] Graph-construction job: extract entities/relations from the corpus + run history into the graph
      store; keep it in sync with new runs.
- [ ] GraphRAG retrieval: multi-hop traversal for relational queries ("which stations in Zone 2 can
      handle capability X, and what was their last bottleneck rate?"). Route relational questions to
      the graph path, free-text to the PA vector path (hybrid retriever).
- [ ] Extend the PA.4 eval set with multi-hop questions; compare flat-RAG vs GraphRAG.

---

## PC — Guardrails + Observability (Safety / Observability)

> **Goal:** Implement the safety boundary CLAUDE.md already mandates but the code lacks, and add real
> tracing so retrieval/answer quality is measurable.

- [ ] **Guardrails / PII boundary.** Input + output sanitization at the chat boundary (the
      DOMPurify/sanitization rule in CLAUDE.md is currently unimplemented). Add a scope/refusal guard,
      PII detection + redaction on logged content, and prompt-injection mitigation for retrieved text.
- [ ] **Tracing.** Wrap the LangGraph in Langfuse (or OTel) — per-turn traces of route, retrieval
      hits, token counts, latency. Replaces the ad-hoc `agent.route.selected` event story.
- [ ] **Observability-driven improvement loop.** Use traces to surface a low-grounding or
      misrouted-query bucket; feed it back into the PA.3/PA.4 tuning. Document one concrete
      before/after improvement.

---

## PD — Real CSP Deployment (Cloud-based AI platform)

> **Goal:** Convert the "Cloudflare Tunnel → local box" story into a credible CSP AI-platform line by
> moving at least one real component to a managed cloud AI service.

- [ ] Pick the component + CSP (recommended: vector store on **Qdrant Cloud / Vertex Vector Search**,
      or the SFT model behind a **Bedrock / SageMaker / Vertex** endpoint). Decide based on cost +
      what best demonstrates the platform skill.
- [ ] Deploy + wire the backend to the managed service via env config (keep local fallback for the
      offline demo). Document setup in `docs/deploy_csp.md`.
- [ ] Update the portfolio narrative (live demo) to show the hybrid local-sim + cloud-AI topology.

---

## Backlog / Lower priority
- [ ] VLM/LAM track (the JD lists VLM/LAM; current training is LLM-only) — only if a concrete
      vision/action use case emerges in the AGV domain.
- [ ] Legacy P6 UE5 production-grade refactor — see [legacy/PLAN.md](legacy/PLAN.md); orthogonal to
      this track.

---

## Definition of "Done" (unchanged from CLAUDE.md)
A task is complete when: code works end-to-end in the demo; the relevant spec doc is updated;
[DONE.md](DONE.md) is updated; the PLAN task is marked `[x]`.
