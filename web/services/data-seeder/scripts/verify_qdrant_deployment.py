"""Verify a seeded VCORE Qdrant deployment without exposing credentials."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse

import httpx


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _embedding(client: httpx.Client, base_url: str, model: str, query: str) -> list[float]:
    response = client.post(
        f"{base_url.rstrip('/')}/v1/embeddings",
        json={"model": model, "input": query},
        timeout=120.0,
    )
    response.raise_for_status()
    data = response.json().get("data") or []
    if not data or not data[0].get("embedding"):
        raise RuntimeError(f"No embedding returned for model '{model}'")
    return data[0]["embedding"]


def verify(
    *,
    qdrant_url: str,
    api_key: str | None,
    collection: str,
    embed_base_url: str,
    embed_model: str,
    expected_points: int,
    expected_document_id: str,
) -> dict[str, object]:
    headers = {"api-key": api_key} if api_key else None
    collection_url = f"{qdrant_url.rstrip('/')}/collections/{collection}"
    with httpx.Client(headers=headers) as qdrant, httpx.Client() as embed_client:
        collection_response = qdrant.get(collection_url, timeout=30.0)
        collection_response.raise_for_status()
        collection_result = collection_response.json().get("result") or {}
        vectors = (
            collection_result.get("config", {})
            .get("params", {})
            .get("vectors", {})
        )

        count_response = qdrant.post(
            f"{collection_url}/points/count",
            json={"exact": True},
            timeout=30.0,
        )
        count_response.raise_for_status()
        point_count = int((count_response.json().get("result") or {}).get("count", 0))

        query = "What should operators do after an AGV collision?"
        vector = _embedding(embed_client, embed_base_url, embed_model, query)
        search_response = qdrant.post(
            f"{collection_url}/points/search",
            json={"vector": vector, "limit": 3, "with_payload": True},
            timeout=30.0,
        )
        search_response.raise_for_status()
        hits = search_response.json().get("result") or []

    top_hit = hits[0] if hits else {}
    top_payload = top_hit.get("payload") or {}
    top_document_id = str(top_payload.get("document_id", ""))
    checks = {
        "status_green": collection_result.get("status") == "green",
        "vector_size_1024": vectors.get("size") == 1024,
        "distance_cosine": str(vectors.get("distance", "")).lower() == "cosine",
        "point_count": point_count >= expected_points,
        "collision_document_ranked_first": top_document_id == expected_document_id,
    }
    return {
        "verified": all(checks.values()),
        "qdrant_host": urlparse(qdrant_url).hostname,
        "collection": collection,
        "status": collection_result.get("status"),
        "vector_size": vectors.get("size"),
        "distance": vectors.get("distance"),
        "point_count": point_count,
        "top_document_id": top_document_id,
        "top_score": top_hit.get("score"),
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-http", action="store_true", help="Permit local non-TLS verification.")
    parser.add_argument("--expected-points", type=int, default=16)
    parser.add_argument("--expected-document-id", default="sop_collision_001")
    args = parser.parse_args()

    try:
        qdrant_url = _required_env("QDRANT_URL")
        api_key = os.getenv("QDRANT_API_KEY") or None
        if not args.allow_http and not qdrant_url.startswith("https://"):
            raise RuntimeError("QDRANT_URL must use HTTPS for cloud verification")
        if not args.allow_http and not api_key:
            raise RuntimeError("QDRANT_API_KEY is required for cloud verification")
        result = verify(
            qdrant_url=qdrant_url,
            api_key=api_key,
            collection=os.getenv("RAG_COLLECTION", "vcore_operations_ko"),
            embed_base_url=os.getenv(
                "EMBED_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            ),
            embed_model=os.getenv("RAG_EMBED_MODEL", "bge-m3"),
            expected_points=args.expected_points,
            expected_document_id=args.expected_document_id,
        )
    except (RuntimeError, httpx.HTTPError, ValueError, KeyError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
