"""Ingest the VCORE knowledge corpus into Qdrant with real embeddings.

PA.1 in PLAN.md / docs/spec_rag.md. Replaces the previous fake SHA-256 vectors with
Ollama embeddings and an actual Qdrant upsert. Two corpus sources:
  - seeds/rag_documents.jsonl  — one short doc per line (schema in spec_rag.md §3.2)
  - seeds/docs/*.md            — long source files, chunked here

Runnable from host anaconda python (Qdrant/Ollama on localhost) or inside the stack
(QDRANT_URL/OLLAMA_BASE_URL pointed at the compose service names). Idempotent: point ids
are derived from document_id + chunk index, so re-running re-indexes in place.

  python scripts/build_qdrant_seed.py            # embed + upsert
  python scripts/build_qdrant_seed.py --dry-run  # parse + chunk only, no network
  python scripts/build_qdrant_seed.py --recreate # drop + recreate the collection first
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = BASE_DIR / "seeds"
DOCS_DIR = SEED_DIR / "docs"

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
# Embeddings use the OpenAI-compatible /v1/embeddings endpoint, which BOTH Ollama and
# llama.cpp serve — switching engines is a base-URL change, no code change (spec_rag.md §4).
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "bge-m3")
COLLECTION = os.getenv("RAG_COLLECTION", "vcore_operations_ko")
DISTANCE = "Cosine"
# Soft target chunk size (characters) for long source files in seeds/docs/.
CHUNK_CHARS = 800
# Stable namespace so a document_id+chunk index always maps to the same Qdrant id.
_ID_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-00000000c0de")

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _point_id(document_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{document_id}:{chunk_index}"))


def load_jsonl_documents() -> list[dict[str, Any]]:
    path = SEED_DIR / "rag_documents.jsonl"
    docs: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Minimal `key: value` YAML frontmatter parse (no external dep)."""
    match = _FRONTMATTER.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for entry in match.group(1).splitlines():
        if ":" in entry:
            key, _, value = entry.partition(":")
            meta[key.strip()] = value.strip()
    return meta, raw[match.end():]


def _chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Group paragraphs into ~size-char chunks, never splitting mid-paragraph."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        if buffer and len(buffer) + len(para) + 2 > size:
            chunks.append(buffer)
            buffer = para
        else:
            buffer = f"{buffer}\n\n{para}" if buffer else para
    if buffer:
        chunks.append(buffer)
    return chunks


def load_markdown_documents() -> list[dict[str, Any]]:
    """Chunk every seeds/docs/*.md file into the rag_documents schema."""
    if not DOCS_DIR.is_dir():
        return []
    docs: list[dict[str, Any]] = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        first_heading = next(
            (ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")),
            path.stem,
        )
        base_id = path.stem
        for index, chunk in enumerate(_chunk_text(body)):
            docs.append(
                {
                    "document_id": f"{base_id}_{index:03d}" if index else base_id,
                    "title": first_heading,
                    "category": meta.get("category", "spec"),
                    "language": meta.get("language", "ko"),
                    "source": meta.get("source", path.name),
                    "text": chunk,
                    "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
                    "zone_id": meta.get("zone_id") or None,
                    "capability": meta.get("capability") or None,
                }
            )
    return docs


def load_corpus() -> list[dict[str, Any]]:
    return load_jsonl_documents() + load_markdown_documents()


def embed(client: httpx.Client, text: str) -> list[float]:
    response = client.post(
        f"{EMBED_BASE_URL}/v1/embeddings",
        json={"model": EMBED_MODEL, "input": text},
        timeout=120.0,
    )
    response.raise_for_status()
    data = response.json().get("data") or []
    if not data or not data[0].get("embedding"):
        raise RuntimeError(f"No embedding returned for model '{EMBED_MODEL}' at {EMBED_BASE_URL}")
    return data[0]["embedding"]


def ensure_collection(client: httpx.Client, dim: int, recreate: bool) -> None:
    url = f"{QDRANT_URL}/collections/{COLLECTION}"
    headers = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else None
    if recreate:
        client.delete(url, headers=headers, timeout=30.0)
    elif client.get(url, headers=headers, timeout=30.0).status_code == 200:
        return
    response = client.put(
        url,
        json={"vectors": {"size": dim, "distance": DISTANCE}},
        headers=headers,
        timeout=30.0,
    )
    response.raise_for_status()


def upsert(client: httpx.Client, points: list[dict[str, Any]]) -> None:
    headers = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else None
    response = client.put(
        f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=true",
        json={"points": points},
        headers=headers,
        timeout=120.0,
    )
    response.raise_for_status()


def build_points(client: httpx.Client, corpus: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for document in corpus:
        payload = dict(document)
        text = payload["text"]
        # Prepend the title so the embedding carries the document's topic (spec §4).
        vector = embed(client, f"{payload.get('title', '')}\n\n{text}".strip())
        points.append(
            {
                "id": _point_id(payload["document_id"], 0),
                "vector": vector,
                "payload": payload,
            }
        )
    return points


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the VCORE knowledge corpus into Qdrant.")
    parser.add_argument("--dry-run", action="store_true", help="Parse + chunk only; no embed/upsert.")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the collection.")
    args = parser.parse_args()

    corpus = load_corpus()
    print(
        f"corpus: {len(corpus)} chunks "
        f"({len(load_jsonl_documents())} jsonl + {len(load_markdown_documents())} from docs/)",
        file=sys.stderr,
    )
    if args.dry_run:
        print(json.dumps({"chunks": len(corpus)}, ensure_ascii=False))
        return

    with httpx.Client() as client:
        points = build_points(client, corpus)
        ensure_collection(client, dim=len(points[0]["vector"]), recreate=args.recreate)
        upsert(client, points)
    print(
        f"upserted {len(points)} points into '{COLLECTION}' "
        f"(dim={len(points[0]['vector'])}, model={EMBED_MODEL}) at {QDRANT_URL}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
