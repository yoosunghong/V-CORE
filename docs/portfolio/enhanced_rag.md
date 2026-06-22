# Enhanced RAG portfolio scenario

## Purpose

This document defines the new portfolio content unlocked by PLAN.md phases PA-PD and the scenes
needed to prove it on camera. The recommended portfolio message is:

> VCORE has evolved from an LLM-controlled digital twin into a grounded operational-intelligence
> platform. It combines multilingual vector retrieval, a typed AGV ontology, guarded LangGraph
> orchestration, regression evaluation, and a managed cloud knowledge index while keeping
> latency-sensitive simulation and inference local.

This is an addition to the existing UE5 control, agent orchestration, SFT, and evaluation story. It
should not replace those sections; it explains how the agent now supports its operational answers
with enterprise knowledge and structured plant state.

## New content for the portfolio document

### 1. From command agent to grounded operations copilot

Describe the original gap plainly: Qdrant existed only as a scaffold and its seed script generated
placeholder hash vectors, while the application performed no retrieval. The completed work turns it
into a live knowledge path:

```text
operator question
  -> LangGraph classify/retrieve nodes
  -> bge-m3 multilingual query embedding
  -> Qdrant candidate search
  -> configurable rerank and score filtering
  -> sanitized knowledge block
  -> cited answer or explicit abstention
```

Portfolio evidence:

- 14 AGV-domain source documents become 16 deterministic Qdrant points after chunking.
- `bge-m3` produces 1024-dimensional embeddings and Qdrant uses cosine distance.
- The knowledge boundary follows a hexagonal `KnowledgeGateway` port, with Qdrant, hybrid graph,
  and null/degraded adapters selected by configuration.
- Retrieval is wired into both general operational Q&A and KPI report generation.

Recommended visual: a before/after architecture panel. The “before” half should show the disconnected
fake-vector scaffold; the “after” half should show the live retrieval node and cited response path.

### 2. Multilingual operational RAG with evidence

Show that an English operator question can retrieve a Korean AGV procedure and ground the answer in
the correct source. Use the collision-response SOP because it has live acceptance evidence and a
clear safety outcome.

Portfolio copy:

> The retriever uses multilingual `bge-m3` embeddings to bridge English and Korean operational
> language. For an AGV collision-response query, the live index ranks `sop_collision_001` first and
> injects the retrieved procedure as untrusted, citable context rather than allowing the model to
> answer from memory alone.

Include the measured retrieval result only with its date and environment. The latest checked-in
evidence is the 2026-06-21 managed-cloud acceptance result (`sop_collision_001` ranked first at
`0.62117743`). Do not present a similarity score as a universal model-quality percentage.

### 3. Hybrid GraphRAG for relational questions

Explain why vector similarity is not enough for questions joining live station state with saved KPI
history. The hybrid gateway routes relational questions to a typed graph and free-text SOP/spec
questions to vector retrieval.

The graph is built from:

- the live station registry (`Cell -> Zone -> Station`),
- deterministic station-type capability mappings (`Station -> Capability`), and
- saved simulation runs and numeric KPIs (`Cell -> Run -> Kpi`).

Use this demonstrated query:

> `Which stations in Zone 2 can handle inspection, and what was their last bottleneck rate?`

The expected graph path is `Zone(B) -> Station -> Capability(inspect)` plus the most recent saved
run's `bottleneck_rate`. The answer context also carries current station readiness, accessibility,
and state.

Recommended visual: animate or progressively reveal the typed multi-hop path beside the chat answer.

### 4. Retrieval quality is regression-gated

Add RAG evaluation as a new subsection of the existing evaluation methodology. The important story
is not merely that retrieval works once, but that the ranking and grounding contract is locked in
tests.

Current baseline:

| Measure | Checked-in threshold | Cases |
|---|---:|---:|
| Vector retrieval recall@5 | 1.00 | 6 |
| Vector retrieval nDCG@5 | 0.88 | 6 |
| Graph retrieval recall@3 | 1.00 | 2 |
| Graph retrieval nDCG@3 | 1.00 | 2 |
| Citation, faithfulness, grounding, abstention | 1.00 each | 3 answer cases |

State clearly that this is a deliberately small portfolio regression set. It proves the pipeline and
prevents known regressions; it is not a statistically broad production benchmark.

### 5. Guardrails and observable quality signals

Show the knowledge boundary as a security boundary, not just a prompt template:

- user input and model output are sanitized;
- common email, phone, Korean resident number, and secret patterns are redacted;
- retrieved text is treated as untrusted and known instruction-like phrases are neutralized before
  prompt injection;
- out-of-domain requests and direct prompt-injection patterns are refused;
- each turn emits a redacted local trace event with route, node path, retrieval-hit count, estimated
  token counts, latency, and `low_grounding` / `possible_misroute` quality buckets.

The concrete improvement loop is the retrieved-document injection path: before the guard, hostile
instructions or PII in a chunk could enter prompts and logs; after the guard, the content is
neutralized/redacted while retrieval-hit observability remains intact.

### 6. Hybrid edge/cloud AI deployment

Add a deployment diagram and data-boundary callout:

```text
local: UE5 + FastAPI/LangGraph + llama.cpp chat model + Ollama bge-m3
                                      |
                                      | authenticated HTTPS
                                      v
cloud: Qdrant Managed Cloud on GCP (knowledge vectors and metadata)
                                      ^
                                      |
local mirror: Qdrant retrieval failback
```

Portfolio copy:

> The managed knowledge index runs on Qdrant Cloud in GCP `australia-southeast1`, while simulation,
> command orchestration, prompts, telemetry, embedding inference, and chat-model inference remain
> local. The backend retries the mirrored local Qdrant index on a cloud retrieval transport/status
> failure without forwarding the cloud API key.

This demonstrates a real CSP-connected AI component and an offline-safe demo topology. It must not
be described as a fully cloud-hosted platform, a production HA deployment, or an SLA-backed service.

### 7. Engineering decisions worth highlighting

Use a compact “decisions and trade-offs” panel:

- Local `bge-m3` keeps document/query embedding data under workstation control; managed Qdrant holds
  only corpus chunks, vectors, and retrieval metadata.
- A common OpenAI-compatible embeddings contract keeps Ollama/llama.cpp serving replaceable by
  configuration.
- Vector search remains the default for prose; the graph path is reserved for relational questions.
- The default reranker is deterministic vector/lexical fusion for offline reliability; an optional
  OpenAI-compatible LLM reranker has lexical fallback.
- Cloud-primary/local-fallback retrieval shares the same collection schema and deterministic point
  IDs.

## Recording plan

Record the following as short, independently usable scenes. Keep the browser, terminal, Qdrant
console, and architecture graphic in separate captures so the final edit can hide endpoints and
secrets safely.

### Scene 1 - The capability gap and completed architecture (15-20 seconds)

**Show:** a simple before/after architecture graphic.

**Record:** zoom from the former disconnected “fake vectors / unused Qdrant” box to the completed
`retrieve -> rerank -> sanitize -> cite` path, then reveal the hybrid graph branch and cloud/local
Qdrant split.

**On-screen proof:** repository paths `app/infrastructure/knowledge_gateway.py`,
`app/domain/ontology.py`, and `docs/deploy_csp.md` may appear briefly.

**Voiceover point:** “The work was not adding a vector database icon; it was connecting ingestion,
retrieval, answer grounding, evaluation, safety, and deployment end to end.”

### Scene 2 - Cloud collection acceptance proof (10-15 seconds)

**Show:** the Qdrant Cloud collection page and sanitized verifier output.

**Record:** collection status green, 1024-dimensional cosine configuration, 16 points, then the
verifier's `verified: true` and first-ranked collision SOP.

**Safety:** crop the cluster hostname if desired and never show the API key, environment file, shell
history containing a key, or browser developer-tools request headers.

### Scene 3 - Cited multilingual SOP answer (20-30 seconds)

**Precondition:** `RAG_ENABLED=true`; cloud or local Qdrant is seeded; Ollama serves `bge-m3`; the
chat LLM is available.

**Type:** `What should operators do after an AGV collision?`

**Show:** the full chat question and grounded operational response. Hold on the document-title
citation. In a split-screen terminal or post-production card, show the retrieval event identifying
`sop_collision_001` and its score.

**Pass condition:** `sop_collision_001` is the first hit and the answer cites the retrieved source.

**Do not claim:** that retrieval events are currently exposed as a polished panel in the React UI.
They are backend/session event evidence and should be shown via sanitized logs, test output, or a
post-production annotation.

### Scene 4 - Honest miss instead of hallucination (15-20 seconds)

**Type:** an AGV-domain question whose answer is deliberately absent from the corpus. Confirm the
exact prompt in rehearsal against the seeded corpus; for example, ask for a nonexistent maintenance
interval for an invented component.

**Show:** the assistant responding with the exact phrase `not in the knowledge base` rather than
inventing a procedure.

**Pass condition:** retrieval returns no supporting chunk or all candidates are excluded, and the
final answer abstains. If the permissive default `RAG_MIN_SCORE=0.0` returns weak context, choose a
cleaner rehearsal prompt or set a justified evaluated threshold; do not stage an answer that the
runtime does not naturally produce.

### Scene 5 - Multi-hop GraphRAG (25-35 seconds)

**Precondition:** `GRAPH_RAG_ENABLED=true`, the control-server station registry is available, and at
least one saved run contains numeric `bottleneck_rate` evidence.

**Type exactly:** `Which stations in Zone 2 can handle inspection, and what was their last bottleneck rate?`

**Show:** the answer listing the matching station(s), readiness/accessibility state, and latest saved
`bottleneck_rate`. Overlay the graph traversal from Zone B to station/capability and run/KPI.

**Pass condition:** the result source is `ontology_graph`, category is `graph_ontology`, and the
vector gateway is not called for the successful graph query.

**Important rehearsal note:** use the English prompt exactly. The current relational router, zone
aliases, and capability parser are English-oriented; an equivalent Korean prompt is not guaranteed
to enter or constrain the graph path.

### Scene 6 - RAG regression gate (15-20 seconds)

**Show:** the baseline JSON beside a clean focused pytest run, then optionally the live evaluation
runner output.

**Record:** recall/nDCG, graph retrieval, citation/faithfulness, and abstention checks passing. Keep
the case counts visible so the result is not presented without scale.

**Pass condition:** focused tests pass and any live run meets the checked-in thresholds.

### Scene 7 - Retrieved-text attack and redacted trace (20-30 seconds)

**Preferred proof:** use the deterministic safety/observability test rather than poisoning the live
cloud corpus immediately before a portfolio recording.

**Show:** a fixture chunk containing an instruction-like phrase and an email, followed by the
sanitized output (`[retrieved-instruction-redacted]`, `[redacted-email]`) and an
`agent.turn.traced` payload that retains `retrieval_hits` without sensitive content.

**Optional live proof:** submit an out-of-scope or direct prompt-injection request and show the scope
refusal. This proves the chat boundary, but the deterministic retrieved-chunk test is stronger proof
of the RAG-specific safety control.

### Scene 8 - Cloud-to-local retrieval failback (20-30 seconds)

**Precondition:** cloud and local collections contain the same corpus; `QDRANT_FALLBACK_URL` points
to the local mirror.

**Record:** first run the collision query against cloud primary. Then override the primary URL with a
deliberately unreachable endpoint, restart/reload the backend configuration, and repeat the same
query. Show the local Qdrant request/result in sanitized backend logs or verifier output.

**Pass condition:** both requests rank `sop_collision_001` first and the application requires no code
change. State that this is retrieval failback, not whole-platform HA.

### Scene 9 - Closing composite (10-15 seconds)

**Show:** UE5 AGVs running, the cited chat response, the ontology path, and the managed Qdrant status
in a four-panel montage.

**Closing line:** “The simulator produces operational state; the ontology joins that state to run
history; vector RAG retrieves the procedure; guardrails constrain the context; and evaluation keeps
the answer contract from silently regressing.”

## Recording order and preflight

Use this order to reduce live-demo risk: Scene 2, Scene 6, Scene 7, Scene 1, then Scenes 3-5 and 8
with the live stack, followed by the closing composite.

Before recording:

1. Confirm the cloud Free Tier cluster is awake and run the sanitized deployment verifier.
2. Confirm local Qdrant contains the same 16 points before attempting failback.
3. Enable both `RAG_ENABLED` and `GRAPH_RAG_ENABLED`; confirm `bge-m3` is available.
4. Create or retain a completed simulation run with `bottleneck_rate` for the graph scene.
5. Rehearse all prompts and save the exact successful wording; do not improvise the graph prompt.
6. Run the focused RAG, graph, safety, and observability tests.
7. Open a clean shell and browser profile; hide `.env`, API keys, hostnames, personal paths, and
   unrelated logs.
8. Capture terminal proof at a readable font size and export the architecture/graph visuals rather
   than filming dense source code for long periods.

## Capability-scope verification

The scenario is within the current implementation scope with the constraints below.

| Scenario claim | Verdict | Repository evidence / constraint |
|---|---|---|
| Real multilingual vector RAG | In scope | Real `bge-m3` embeddings, Qdrant search, rerank, and knowledge prompt injection are implemented and tested. |
| Cited SOP/general-chat answer | In scope, live-stack dependent | `general_chat` flows through the retrieve node; report generation also receives knowledge. Requires RAG enabled and both embedding and chat services available. |
| Honest abstention | In scope, rehearse | Prompt and evaluation contract require `not in the knowledge base`; permissive score filtering means the chosen live prompt must be verified. |
| Typed multi-hop GraphRAG | In scope with narrow query grammar | The in-process typed graph joins station/capability state with the latest saved KPI. Current relational parsing is English-oriented and rule-based. |
| Persistent enterprise graph database, RDF/OWL, or learned graph extraction | Out of scope | The graph is rebuilt in process from structured registry/run data; it is not Neo4j, RDF/OWL, or LLM entity extraction. |
| Station-specific historical bottleneck rate | Out of scope | The current retriever appends the latest cell/run `bottleneck_rate`; it does not prove that the value belongs to each returned station. Word the answer as “latest saved run bottleneck rate.” |
| Cross-encoder reranking | Out of scope as a current claim | Default is deterministic vector/lexical fusion; optional LLM reranking exists. No cross-encoder implementation should be claimed. |
| RAG quality regression suite | In scope | Deterministic pytest gates and a live runner cover retrieval, graph retrieval, grounding, citations, faithfulness, and abstention. The dataset is intentionally small. |
| RAG security and PII protection | In scope with bounded patterns | Sanitization, regex-based PII/secret redaction, retrieved-instruction neutralization, and scope refusal exist. Do not claim comprehensive DLP or adversarial robustness. |
| Hosted Langfuse or full OpenTelemetry backend | Out of scope | The implementation emits a local OTel-shaped trace event; there is no hosted trace UI/exporter in the current code. |
| Retrieval/trace dashboard in the React overlay | Out of scope | The backend emits the events, but the current frontend log filter does not render dedicated `agent.retrieval` or `agent.turn.traced` panels. Use sanitized terminal/test evidence or post-production graphics. |
| Managed cloud vector store | In scope | Qdrant Managed Cloud was live-verified on 2026-06-21 with authenticated HTTPS. Re-verify cluster availability immediately before recording. |
| Automatic cloud-to-local Qdrant retry | In scope | The Qdrant adapter retries its configured local endpoint after a cloud HTTP/transport failure and omits the cloud key on fallback. |
| Fully cloud-hosted or production-HA platform | Out of scope | UE5, backend, embedding/chat inference, and telemetry remain local; only the vector store is managed cloud. Qdrant Free Tier has no production SLA. |

## Final recommendation

The strongest portfolio sequence is: **cited multilingual SOP answer -> typed multi-hop GraphRAG ->
regression metrics -> retrieved-text safety -> real cloud/local failback**. Together these scenes show
product value, architecture depth, measurable quality, safety engineering, and deployment judgment.

Keep all numerical claims tied to the checked-in baseline or a dated recording-time verifier run.
With the limitations above stated precisely, every recommended scene is either directly supported by
the current runtime or by a deterministic repository test and stays within present capability.
