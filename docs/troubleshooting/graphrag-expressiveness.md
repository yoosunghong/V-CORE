# GraphRAG Expressiveness Limitation

> Tracks the portfolio limitation **"GraphRAG 표현력 제한"** from
> [portfolio/PORTFOLIO.md](../portfolio/PORTFOLIO.md) (한계 및 개선점). Records the problem, the
> remediation process, what was changed, and the gaps that remain.

## Summary

The PB GraphRAG path had three expressiveness limits: (1) the graph was rebuilt in-process on every
retrieval (no persistent store), (2) the relational query grammar was **English rule-based only**,
and (3) KPI evidence was reported as a single **cell-global** `bottleneck_rate`, not attributed per
station/zone.

A first pass closed (2) and (3) — Korean relational parsing and station-level (per-zone) KPI
attribution. A follow-up pass (2026-06-22) closed (1) **without** standing up a new service: the
in-process graph is now a **memoized projection with incremental invalidation** — built once and
reused across queries, rebuilt only when the station registry or saved-run history actually changes.
This converts O(queries) rebuilds into O(state-changes) rebuilds while staying inside the demo's
"no extra service" design. A persistent external graph store (Neo4j/RDF) remains a CSP-scale future
step, but the "rebuilt for every query" cost is gone.

## Problem

- **English-only grammar.** `is_relational_query`, `parse_zone`, and `parse_capability` in
  `app/domain/ontology.py` matched only English signals (`which stations`, `zone`, `capability`,
  `inspection`/`load`/…). A Korean operator asking `존 2에서 검사를 처리할 수 있는 스테이션과
  마지막 병목률은?` fell through to flat vector retrieval and lost the multi-hop traversal — even
  though the product is Korean-first.
- **No station/zone KPI attribution.** `GraphRagRetriever.retrieve` appended one line —
  `Latest bottleneck_rate: <x> from run <id>` — using `latest_metric` over the whole cell. Two
  stations in different zones got the *same* bottleneck number, so the "what was *their* last
  bottleneck rate?" half of the demo query was answered cell-globally, not per station.
- **In-process rebuild on every query.** `OntologyGraphBuilder.build` ran a full graph
  construction (allocating every `OntologyNode`/`OntologyEdge` and both adjacency maps) on *each*
  relational query, even when the station registry and saved runs had not changed since the last
  query. The graph was never persisted or reused — each retrieval paid the full build cost.

## Root Cause

The PB graph was built as the minimum typed multi-hop retriever over the live station registry +
saved runs (spec_ontology.md), scoped to the English demo query. The Korean grammar and per-station
KPI attribution were never in PB's scope; the in-process rebuild was a deliberate "no extra service"
demo choice.

## Remediation Process

1. **Reproduced the gap** with the Korean form of the canonical demo query and confirmed
   `is_relational_query` returned `False`, so it never reached the graph path.
2. **Extended the grammar.** Added Korean relational signals (`스테이션`, `존`/`구역`, `역량`,
   `병목률`, `처리할 수 있`, …) to `is_relational_query`, Korean zone aliases (`존 2`/`구역 2` → Zone
   B, etc.) to `ZONE_ALIASES`, and Korean capability aliases (`검사`→inspect, `적재`→load,
   `픽업`→pickup, `하역`→unload, `작업`→process, `충전`→charge, `배터리`→battery) to
   `parse_capability`. The regex word-boundaries already exclude only ASCII alnum, so Korean tokens
   surrounded by Korean text match cleanly.
3. **Added per-zone KPI attribution.** New `latest_zone_metric(runs, zone, metric)` reads the latest
   run's `zone_heatmap` (`{"A": 0.12, "B": 0.47, ...}`) and returns the zone-resolved value. Each
   station line now appends `Last zone bottleneck_rate: <value> (run <id>)`; the cell-global value is
   relabeled `Latest cell bottleneck_rate` and kept as a labelled fallback.
4. **Added regression tests** for the Korean relational query and the per-zone attribution, and
   updated the existing assertion for the relabeled cell-global line.
5. **Extended the eval set** with two Korean graph cases (`graph_multi_hop_ko`,
   `graph_station_capability_ko`) and re-locked the deterministic graph baseline.
6. **Eliminated the per-query rebuild (2026-06-22).** Split `OntologyGraphBuilder.build` into a
   cached entry point plus the original construction (`_build`). `build` computes a content
   fingerprint of `(stations, runs)` — `hashlib.sha1` over each station's `model_dump(mode="json")`
   plus each run's `run_id`/`status`/`created_at`/`started_at`/`ended_at`/`kpis_json` — and serves a
   memoized `OntologyGraph` keyed on it from a small LRU (`cache_size=8`, `OrderedDict`). A rebuild
   (`_build`, which bumps `self.builds`) only runs when the fingerprint changes, i.e. when the cell
   state or run history actually changes. The cached graph is shared read-only by the retriever, so
   no defensive copy is needed. Added regression tests: same inputs reuse the same graph object
   (`builds == 1`); a new run invalidates the fingerprint and triggers exactly one rebuild
   (`builds == 2`); and three relational queries over unchanged state build the graph once.

## What Changed

| File | Change |
|---|---|
| `web/services/chatbot-backend/app/domain/ontology.py` | Korean signals in `is_relational_query`; Korean entries in `ZONE_ALIASES` + `parse_capability`; new `latest_zone_metric`; per-station zone bottleneck line; cell-global line relabeled; **memoized graph: fingerprint cache + LRU in `OntologyGraphBuilder.build`, construction moved to `_build`, `builds` counter** |
| `web/services/chatbot-backend/tests/test_rag_retrieval.py` | new Korean-query + per-zone-attribution tests; existing cell-global assertion updated; **memoization tests (cache reuse / invalidation / one build across queries)** |
| `web/services/chatbot-backend/app/benchmarks/rag_cases.py` | 2 Korean graph cases + baseline rankings |
| `docs/spec/spec_ontology.md` §4 | documents Korean grammar + station-level attribution |

## Verification

```
python -m pytest tests/test_rag_retrieval.py -q   # graph + Korean + attribution + memoization pass
python -m pytest -q                               # 127 passed
```

Behaviour confirmed: `존 2에서 검사를 처리할 수 있는 스테이션과 마지막 병목률은?` now routes to the
graph path and returns `ontology_station_b_inspect` with `Station 3`; with a `zone_heatmap` run the
Zone-B station reports `Last zone bottleneck_rate: 0.47` alongside `Latest cell bottleneck_rate:
0.39`.

## Remaining Gaps (next steps)

- **External persistent graph store.** The per-query rebuild is fixed (the graph is now an
  in-process memoized projection rebuilt only on state change). What remains for CSP scale is a
  *cross-process / durable* store: projecting the same node/edge model into Neo4j / RDF / a managed
  graph service with incremental sync on each new run, so the graph survives process restarts and is
  shared across replicas. Deferred: it adds a service without changing demo capability, and the
  in-process cache already removes the rebuild-per-query cost.
- **Deeper constraint grammar.** Parsing is alias/keyword based (one zone + one capability). It does
  not yet handle compound constraints ("Zone 2 **or** 3", "inspection **and** charging", numeric
  thresholds like "병목률 30% 이상인 존"). A small typed query parser would generalise this.
- **Attribution beyond bottleneck.** `latest_zone_metric` is wired for `bottleneck_rate`. The same
  mechanism should surface per-zone `throughput`/`avg_wait` when runs carry zone-resolved KPIs.

## Lessons Learned

- A keyword-routed retriever silently degrades for any unhandled language: the Korean query didn't
  error, it just bypassed the graph — so the failure was invisible without a Korean eval case.
- Cell-global KPI reporting reads as "answered" while actually dropping the per-entity half of a
  multi-hop question; labelling (`cell` vs `zone`) makes the granularity explicit and testable.
