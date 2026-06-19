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

`OntologyGraphBuilder` rebuilds the graph from the live station registry and the latest saved runs.
The hybrid gateway calls it at retrieval time, so new runs become queryable without a separate
daemon. A future CSP version can persist the same node/edge projection into Neo4j, RDF, or a managed
graph service, but the demo does not need another service.

The optional `scripts/export_ontology_graph.py` job exports the same projection to JSON for
inspection and portfolio evidence.

## 4. Hybrid Retrieval

`HybridGraphKnowledgeGateway` wraps the PA `QdrantKnowledgeGateway`.

- Relational questions route to graph retrieval. Signals include `which stations`, `zone`,
  `capability`, `bottleneck`, and `last KPI`.
- Free-text SOP/spec questions route to PA vector retrieval.
- If a relational question produces no graph answer, the gateway falls back to vector retrieval.

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
