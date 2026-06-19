# Knowledge source documents (RAG corpus)

Drop **long-form** operational source files here (Markdown `.md`; PDF support via the chunker).
The PA.1 ingest job chunks every file in this folder into the `rag_documents.jsonl` schema
(see [docs/spec_rag.md](../../../../../docs/spec_rag.md) §3.2) and indexes them into the Qdrant
`vcore_operations_ko` collection.

For **short facts**, add a single line to `../rag_documents.jsonl` instead — no file needed.

## Conventions
- One topic per file. Filename → `source`/`document_id` basis.
- Start each file with an `# H1` title (used as the citation `title`).
- Korean primary (`language: ko`); add English files with an `_en` suffix.
- Tag a file to a zone/capability by putting `zone_id:` / `capability:` in YAML frontmatter
  (optional) — the chunker copies it into each chunk's payload.

## Categories (`category` field)
`sop` · `safety` · `spec` · `playbook` · `handoff` · `run_report`
