# RAG Eval-Set Scale Limitation

> Tracks the portfolio limitation **"RAG 평가셋 규모 제한"** from
> [portfolio/PORTFOLIO.md](../portfolio/PORTFOLIO.md) (한계 및 개선점). Records the problem, the
> remediation process, what was changed, and the gaps that remain.

## Summary

The PA.4 RAG regression baseline was deliberately tiny — **6 retrieval + 2 graph + 3 answer
cases** — enough to gate pipeline contracts and known regressions, but not a statistically
meaningful production benchmark. The single most concrete weakness: the corpus
(`vcore_operations_ko`) is **Korean**, yet every eval query was **English**, so the platform's
multilingual-retrieval claim was never regression-tested.

This pass scaled the deterministic eval set to **16 retrieval + 4 graph + 6 answer cases**, with
the new cases concentrated on the Korean-query gap and broader corpus coverage, and re-locked the
green baseline.

## Problem

- **No Korean queries.** `app/benchmarks/rag_cases.py` held 6 retrieval cases, all English, against
  a Korean corpus. The "영문 질의로 한국어 절차서를 찾는다" multilingual story was demonstrated once in
  manual acceptance (`sop_collision_001` @ 0.62 on 2026-06-21) but never regression-gated, and the
  reverse (Korean query → Korean doc, the actual operator path) was untested.
- **Thin corpus coverage.** Of 14 corpus documents, the retrieval cases exercised ~8. Startup,
  speed, throughput, live-status, and dispatch-failure docs had no labeled query.
- **Few answer-grounding cases.** Only 3 (`answer_collision_grounded`, `answer_bottleneck_grounded`,
  `answer_honest_miss`), all English. Korean grounded-citation and Korean abstention were unverified.
- **Not a statistical benchmark.** The set proves "the contract holds and known regressions are
  blocked" — it is not sized for confidence intervals, hard-negative mining, or production drift
  detection. (This part remains true; see *Remaining gaps*.)

## Root Cause

The PA.4 baseline ([docs/benchmark/RAG_PA4_BASELINE.json](../benchmark/RAG_PA4_BASELINE.json)) was
scoped as a *contract gate*, not a *quality benchmark*. It was intentionally small so CI could run
it deterministically (fixture rankings + fixture answers) without a live Qdrant or LLM stack. The
limitation is one of scope, not correctness — but the English-only queries were a genuine blind spot
for a Korean-first product.

## Remediation Process

1. **Audited the corpus vs. the cases.** Mapped each of the 14 `rag_documents.jsonl` documents to
   whether any retrieval case targeted it; found the uncovered docs and the language gap.
2. **Added broader English retrieval cases** (startup, throughput, live status, dispatch failure) so
   the previously-uncovered corpus docs each have a labeled query.
3. **Added Korean query variants** — the core fix. Korean retrieval cases for collision, Zone-2
   bottleneck, bottleneck definition, KPI definition, station kinds, and low-battery handling, each
   labeled to its Korean source document.
4. **Added Korean answer-grounding cases** — a Korean grounded-citation case
   (`answer_collision_grounded_ko`), a Korean live-status case (`answer_status_grounded_ko`), and a
   Korean abstention case (`answer_honest_miss_ko`).
5. **Kept hard-negative behaviour gated.** False grounding (wrong/uncited citation, hallucinated
   term, missing required term) is exercised by
   `test_answer_grounding_flags_unsupported_uncited_claims` — confirmed it still flags `grounded =
   False`.
6. **Re-locked the baseline.** Updated the deterministic fixture rankings so each relevant document
   ranks first (recall@5 = 1.0, nDCG = 1.0), bumped the case counts in `RAG_PA4_BASELINE.json`, and
   ran the suite green.

## What Changed

| File | Change |
|---|---|
| `web/services/chatbot-backend/app/benchmarks/rag_cases.py` | retrieval cases 6→16 (4 EN + 6 KO added); graph cases 2→4 (2 KO added); answer cases 3→6 (3 KO added); fixture rankings extended |
| `web/services/chatbot-backend/tests/test_rag_eval.py` | expected answer case-id set updated to the 6 cases |
| `docs/benchmark/RAG_PA4_BASELINE.json` | counts 16/6/4, expansion note, date 2026-06-22 |
| `docs/spec/spec_rag.md` §7 | documents the expansion and the multilingual gap it closed |

## Verification

```
python -m pytest tests/test_rag_eval.py tests/test_rag_retrieval.py -q   # 20 passed
python -m pytest -q                                                       # 125 passed
```

Deterministic thresholds held: retrieval recall@5 = 1.0 / nDCG = 1.0, graph recall@3 = 1.0 /
nDCG = 1.0, answer citation/faithfulness/grounded/abstention = 1.0 across the larger set.

## Remaining Gaps (next steps)

- **Operational-log-derived hard negatives.** The set is still author-curated. Mining real chat
  logs for near-miss queries (e.g. "충전 스테이션 동작?" where the corpus says it's unimplemented)
  would produce true hard negatives the abstention guard must catch.
- **Statistical sizing.** Still a contract gate, not a benchmark with confidence intervals. A
  production benchmark needs tens of queries per category and a live-stack run (not just fixtures)
  scored against `scripts/eval_rag_retrieval.py`.
- **Live-stack regression.** Current gates use fixture rankings so CI needs no Qdrant/LLM. A
  periodic live run (Qdrant Managed Cloud + bge-m3) should be compared against this baseline to
  catch embedding/corpus drift the fixtures can't see.

## Lessons Learned

- A "tiny but green" eval set can hide a whole-language blind spot: a Korean corpus tested only with
  English queries looks healthy while the primary user path is unmeasured.
- Keep contract gates deterministic (fixtures) **and** separately schedule a live-stack run — they
  answer different questions ("did the contract break?" vs. "did retrieval quality drift?").
