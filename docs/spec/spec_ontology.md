# spec_ontology.md - VCORE GraphRAG / Ontology

> **Status:** Active (PB in [PLAN.md](../PLAN.md)). This extends the PA vector RAG path in
> [spec_rag.md](spec_rag.md) with a typed AGV-cell graph for relational questions.

## 1. Goal

PB adds ontology-grounded retrieval for questions that flat vector search handles poorly:

- Which stations are in a zone?
- Which stations can handle a capability?
- What was the latest KPI/bottleneck evidence for the related run or zone?

The graph is intentionally local and typed for the demo. It is built from structured state already
owned by the platform, not from hand-authored prose:

- Station registry from the control server (`Station.station_id`, `station_type`, `zone`,
  `task_ready`, `accessible`, `state`).
- Saved simulation runs from the session repository (`SimulationRun.kpis_json`, `result_json`).
- Capability rules derived from the station type contract used by the UE5/control-server domain.

## 2. Ontology

### Node types

| Type | Id example | Source |
|---|---|---|
| `Cell` | `cell:cell_demo` | station registry |
| `Zone` | `zone:B` | station registry |
| `Station` | `station:2` | station registry |
| `Capability` | `capability:process` | station type mapping |
| `Run` | `run:run_abc` | repository run history |
| `Kpi` | `kpi:bottleneck_rate` | run KPI payload |

### Edge types

| Edge | Meaning |
|---|---|
| `CONTAINS` | cell -> zone, zone -> station |
| `HAS_CAPABILITY` | station -> capability |
| `HAS_RUN` | cell -> run |
| `MEASURED` | run -> KPI |
| `AFFECTS_ZONE` | run/KPI -> zone when the KPI payload has zone evidence |

Station capability mapping is deterministic:

- `loading`: `load`, `pickup`, `station_task`
- `work`: `process`, `work`, `station_task`
- `inspection`: `inspect`, `inspection`, `qa`
- `unloading`: `unload`, `dropoff`, `station_task`
- `charger`: `charge`, `battery`

## 3. Construction And Sync

`OntologyGraphBuilder` projects the graph from the live station registry and the latest saved runs.
The hybrid gateway calls it at retrieval time, so new runs become queryable without a separate
daemon.

**Memoized projection with incremental invalidation (2026-06-22).** The first cut rebuilt the
whole graph on *every* relational query. The builder now memoizes the projection on a content
fingerprint of `(stations, runs)` (a SHA-1 over each station's `model_dump` plus each run's
id/status/timestamps/`kpis_json`). A query reuses the cached graph and a rebuild only fires when the
station registry or saved-run history actually changes — turning per-query rebuilds into per-change
rebuilds. The cache is a small LRU (`cache_size=8`) so interleaved cell states still hit; the
returned graph is shared and treated as read-only by `GraphRagRetriever`. `builder.builds` exposes
the rebuild count for tests/observability. This keeps the graph an in-process,
persistent-until-changed store without standing up a separate graph service. A future CSP version can
still persist the same node/edge projection into Neo4j, RDF, or a managed graph service with
incremental sync, but the demo does not need another service.

The optional `scripts/export_ontology_graph.py` job exports the same projection to JSON for
inspection and portfolio evidence.

## 4. Hybrid Retrieval

`HybridGraphKnowledgeGateway` wraps the PA `QdrantKnowledgeGateway`.

- Relational questions route to graph retrieval. Signals include `which stations`, `zone`,
  `capability`, `bottleneck`, and `last KPI`.
- **Korean relational queries (expressiveness expansion, 2026-06-22):** `is_relational_query`,
  `parse_zone`, and `parse_capability` now also recognise Korean signals (`스테이션`, `존`/`구역`,
  `역량`, `병목률`, `처리할 수 있`) and entity aliases (`검사`→inspect, `적재`→load, `충전`→charge,
  `존 2`/`구역 2`→Zone B, …), so a query like `존 2에서 검사를 처리할 수 있는 스테이션과 마지막
  병목률은?` traverses the same multi-hop path the English query does. Previously the grammar was
  English-only.
- Free-text SOP/spec questions route to PA vector retrieval.
- If a relational question produces no graph answer, the gateway falls back to vector retrieval.

### Station-level KPI attribution (2026-06-22)

The first GraphRAG cut reported a single cell-global `bottleneck_rate` for every station. The
retriever now attributes a **per-zone** bottleneck rate to each station from the latest run that
carries a `zone_heatmap` (`{"A": 0.12, "B": 0.47, ...}`) via `latest_zone_metric(runs, zone,
metric)`. Each station line gains `Last zone bottleneck_rate: <value> (run <id>)` and the cell-global
value is kept as a clearly-labelled fallback (`Latest cell bottleneck_rate`). When no run has
zone-resolved evidence the station simply omits the zone line and the cell-global fallback stands.

Process notes, remaining gaps (persistent graph store, deeper constraint grammar), and next steps:
[../troubleshooting/graphrag-expressiveness.md](../troubleshooting/graphrag-expressiveness.md).

Graph results are returned as `RetrievedChunk` objects with `category="graph_ontology"` and
`source="ontology_graph"` so the existing prompt/citation path can cite them without a new LLM API.

## 5. Multi-Hop Demo Query

Question:

```text
Which stations in Zone 2 can handle inspection, and what was their last bottleneck rate?
```

Traversal:

```text
Zone(B/Zone 2) -> CONTAINS -> Station(3)
Station(3) -> HAS_CAPABILITY -> Capability(inspect)
Cell(cell_demo) -> HAS_RUN -> latest Run -> MEASURED -> Kpi(bottleneck_rate)
```

Answer context summarizes station readiness/accessibility and the latest run KPI evidence, with a
citation title such as `Ontology: Zone B stations for capability inspect`.

## 6. Evals

PB extends PA.4 with `GRAPH_RAG_RETRIEVAL_CASES` and deterministic `GRAPH_RAG_BASELINE_RANKINGS`.
The graph baseline compares against flat RAG by requiring graph ontology chunks to satisfy multi-hop
queries that need both station/capability facts and KPI history.
