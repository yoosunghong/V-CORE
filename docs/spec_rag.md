# spec_rag.md — VCORE RAG / Knowledge Retrieval

> **Status:** Active (PA in [PLAN.md](../PLAN.md)). This is the design doc for the RAG track.
> Write/update this **before** writing retrieval code (CLAUDE.md "documentation first").
> Related: [spec_virtual_process.md](spec_virtual_process.md) (chatbot architecture),
> [spec_ontology.md](spec_ontology.md) (PB — GraphRAG, to be written).

---

## 1. Goal & scope

Make the dead Qdrant scaffold live so the agent grounds its answers in a real operational corpus.
This closes four currently-missing capabilities at once:

- **Enterprise Knowledge Store** — a real, queryable corpus of AGV-cell operational knowledge.
- **RAG** — retrieval-augmented grounding of the `report` and `general_chat` answers.
- **IR optimization** — embeddings + reranking + retrieval-quality evals.
- **Context Engineering** — retrieved context injected into the prompt under a token budget.

**Non-goals for PA:** the graph/ontology multi-hop retrieval is **PB** (GraphRAG); PA is flat
vector retrieval only. Guardrails over retrieved text are **PC**.

---

## 2. Current state (what exists today)

| Piece | Location | State |
|---|---|---|
| Qdrant service | `web/docker-compose.yml` | provisioned, running, **unused by the app** |
| Collection schema | `web/infra/vector-db/init/collections.json` | was `farm_operations_ko` (stale) → renamed `vcore_operations_ko` |
| Seed corpus | `web/services/data-seeder/seeds/rag_documents.jsonl` | was farm/greenhouse docs → **replaced** with AGV-domain docs (PA.0) |
| Ingest job | `web/services/data-seeder/scripts/build_qdrant_seed.py` | emits **fake SHA-256 vectors**; no real embedding, no upsert to Qdrant |
| Backend retrieval | `web/services/chatbot-backend/app/**` | **none** — zero embedding/retrieval/qdrant imports |

PA replaces the stale corpus, swaps fake vectors for a real embedding model, and adds a retrieval
node + `KnowledgeGateway` port to the backend.

---

## 3. Corpus

### 3.1 Two sources of knowledge

1. **Authored documents** — operating procedures, equipment specs, safety rules, scenario
   playbooks. Authored by hand and dropped into the data-seeder (see §3.3).
2. **Run/KPI history** — past `SimulationRun` reports + `kpis_json` from Postgres, ingested
   programmatically (PA.2). Not uploaded by hand.

### 3.2 Document schema (JSONL, one object per line)

`web/services/data-seeder/seeds/rag_documents.jsonl`:

```json
{
  "document_id": "sop_collision_001",
  "title": "AGV 충돌 발생 시 대응 절차",
  "category": "sop",
  "language": "ko",
  "source": "ops_manual",
  "text": "...",
  "tags": ["collision", "safety"],
  "zone_id": null,
  "capability": null
}
```

| Field | Type | Purpose |
|---|---|---|
| `document_id` | keyword | stable id, used as Qdrant point id basis |
| `title` | text | shown in citations |
| `category` | keyword | `sop` / `safety` / `spec` / `playbook` / `handoff` / `run_report` |
| `language` | keyword | `ko` (primary) / `en` |
| `source` | keyword | provenance (`ops_manual`, `equipment_spec`, `run_history`, …) |
| `text` | text | the chunk body (embedded) |
| `tags` | keyword[] | retrieval filters (e.g. `collision`, `throughput`) |
| `zone_id` | keyword? | ties a doc to a cell zone (GraphRAG/PB filter) |
| `capability` | keyword? | ties a doc to a station capability |

### 3.3 Uploading a document (operator workflow)

- **Short facts** → add a line to `seeds/rag_documents.jsonl`.
- **Long source files** (Markdown/PDF SOPs, spec sheets) → drop into `seeds/docs/` (PA.1 adds a
  chunker that splits these into the schema above). Re-run the ingest job to (re)index.

### 3.4 Categories grounded in the real domain

The corpus describes the *actual* VCORE entities, so retrieval is meaningful:
`EStationKind` (Pickup/Dropoff/Charger/Inspection), `ZoneId`, `CapabilityTags`, and the KPI set
(`throughput` / `avg_wait` / `collision_risk` / `uptime` / `bottleneck_rate`).

---

## 4. Embeddings & vector store

- **Embedding model:** `bge-m3` (multilingual, strong KO; **1024-dim**), set via `RAG_EMBED_MODEL`.
  Served via the **OpenAI-compatible `/v1/embeddings`** endpoint, which **both Ollama and llama.cpp
  expose** — so the serving engine is a base-URL change (`EMBED_BASE_URL`), no code change. Default
  is the host Ollama (`:11434`); to consolidate onto llama.cpp later, run a `bge-m3` GGUF on a
  `llama-server --embeddings` instance and repoint `EMBED_BASE_URL`. `collections.json` `vector_size`
  is 1024 to match.
  > **Engine split (decided 2026-06-19):** the chat/routing LLM stays on **llama.cpp** under
  > `adapter_toggle` (per-request LoRA scaling is llama.cpp-only); embeddings run on **Ollama**
  > (`bge-m3`) — independent, no GPU contention (embeddings can run CPU). Deliberate, documented split.
- **Store:** Qdrant `vcore_operations_ko`, distance `Cosine`, payload schema = the §3.2 fields.
- **Chunking:** ~300–500 token chunks, title prepended to each chunk for context. One Qdrant point
  per chunk; `document_id` + chunk index → deterministic point id.

---

## 5. Backend wiring (hexagonal)

### 5.1 Port (`application/ports.py`)

```python
class KnowledgeGateway(Protocol):
    async def retrieve(
        self,
        query: str,
        correlation_id: str,
        *,
        top_k: int = 5,
        filters: dict[str, str] | None = None,   # e.g. {"zone_id": "2"}
    ) -> list[RetrievedChunk]: ...
```

`RetrievedChunk` (new domain model): `document_id`, `title`, `text`, `score`, `source`, `category`.

### 5.2 Adapters (`infrastructure/`)

- `QdrantKnowledgeGateway` — embeds the query (`/v1/embeddings`, `EMBED_BASE_URL`) → Qdrant search →
  `RetrievedChunk[]`.
- `NullKnowledgeGateway` — returns `[]` (mock mode / Qdrant down), so the demo never hard-fails.
  Selected via `RAG_ENABLED` in `infrastructure/container.py` (mirrors the existing client-mode pattern).

### 5.3 Graph node (`application/multi_response_graph.py`)

Add a `retrieve` node that runs **before** the answer-producing nodes and writes
`state["retrieved"]`. Wire it into:

- `_report_general_chat` (currently `application/multi_response_graph.py:261`) — ground free-text Q&A.
- the report path (`generate_report` in `OllamaLlmGateway`, prompt `prompts/templates/report_user.txt`)
  — ground the KPI verdict with the relevant SOP/spec.

Emit an `agent.retrieval` `DomainEvent` (`{query, hits:[{document_id,title,score}]}`) so retrieval is
visible in the overlay and (PC) traceable.

### 5.4 Prompt changes

- Extend `report_user.txt` / the general-chat prompt with a `참고 문서:` block listing retrieved
  chunks + a citation instruction.
- **Grounding guard (PA.3):** instruct the model to answer `"not in the knowledge base"` when no
  chunk is relevant, instead of hallucinating. (Hardened in PC.)

### 5.5 Config (`infrastructure/config.py`)

New settings (env-overridable, following the existing pattern):
`rag_enabled` (`RAG_ENABLED`, default `false`), `qdrant_url` (`QDRANT_URL`),
`rag_collection` (`RAG_COLLECTION=vcore_operations_ko`), `rag_embed_model` (`RAG_EMBED_MODEL`),
`rag_top_k` (`RAG_TOP_K=5`), `embed_base_url` (`EMBED_BASE_URL`, default the Ollama base — the
engine-split lever that keeps embeddings on Ollama while the LLM serves from llama.cpp).

> **Status (PA.2 done 2026-06-19):** port + `QdrantKnowledgeGateway`/`NullKnowledgeGateway`
> adapters, the `retrieve` node on the `general_chat` branch, report-path grounding via
> `_report_retrieval_query`, the `agent.retrieval` event, and the prompt blocks are all implemented
> behind `RAG_ENABLED`. PA.3 adds the `"not in the knowledge base"` guard and reranking.

---

## 6. IR optimization (PA.3)

- **Candidate fetch + rerank.** Qdrant retrieves `RAG_FETCH_K` candidates (default `max(top_k, 10)`)
  and the backend returns the best `RAG_TOP_K` after reranking. The production reranker is
  configurable:
  - `RAG_RERANK_MODE=lexical` (default): deterministic Korean/English token-overlap reranker fused
    with the vector score. This is the offline-safe fallback and is fast enough for the local demo.
  - `RAG_RERANK_MODE=llm`: optional LLM rerank pass over the same candidates using the
    OpenAI-compatible chat endpoint (`RAG_RERANK_BASE_URL`, `RAG_RERANK_MODEL`). If the call fails or
    returns invalid ids, the adapter falls back to lexical reranking.
- **Score filtering.** `RAG_MIN_SCORE` (default `0.0`) can suppress weak candidates before prompt
  injection. PA.3 keeps the threshold permissive by default because the corpus is still tiny; the
  eval script reports the score distribution for tuning.
- **Labeled tuning set.** `app/benchmarks/rag_cases.py` contains the first small query set. The
  `scripts/eval_rag_retrieval.py` runner measures recall@k and nDCG@k against a live Qdrant stack and
  can compare `top_k` / `fetch_k` / rerank modes without touching the application graph.
- **Prompt grounding guard.** Citation prompts now require document-title citations when context is
  present and the exact miss response `"not in the knowledge base"` when no retrieved chunk supports
  the answer. This is a prompt-level PA.3 guard; PC later adds input/output safety enforcement.

---

## 7. Evals (PA.4 — regression)

RAG regression lives beside the existing benchmark harness:

- **Retrieval quality:** `app/benchmarks/rag_cases.py` defines labeled query -> relevant
  `document_id` cases and deterministic PA.4 fixture rankings. `app/benchmarks/rag_eval.py`
  measures recall@k and nDCG@k.
- **Answer grounding / faithfulness:** `RagAnswerCase` fixtures check whether answers cite retrieved
  chunks, include required grounded terms, avoid forbidden hallucinated terms, and honestly abstain
  with `"not in the knowledge base"` when retrieval returns nothing.
- **Locked baseline:** [benchmark/RAG_PA4_BASELINE.json](benchmark/RAG_PA4_BASELINE.json) records the
  PA.4 thresholds. `tests/test_rag_eval.py` gates the deterministic baseline in pytest, while the
  live runner can compare a real stack run with:

  ```powershell
  python scripts/eval_rag_retrieval.py --baseline ../../../docs/benchmark/RAG_PA4_BASELINE.json
  ```

The current PA.4 baseline is intentionally small (6 retrieval cases, 3 answer-grounding cases) but
fully regression-gated. PB extends the same harness with multi-hop GraphRAG cases.

---

## 8. Demo scenarios this unlocks

1. **Grounded diagnosis** — "왜 처리량이 떨어졌어?" → cites the bottleneck/Zone-2 playbook.
2. **Operational Q&A** — "충돌이 나면 어떻게 대응해?" → cites `sop_collision_001`.
3. **Honest miss** — out-of-corpus question → "지식 베이스에 없는 내용입니다."
4. (PB) **Multi-hop** — "Zone 2에서 capability X를 처리할 수 있는 station과 마지막 병목률은?"

See [demo_script.md](demo_script.md) (to be extended) for the recorded-clip versions.
