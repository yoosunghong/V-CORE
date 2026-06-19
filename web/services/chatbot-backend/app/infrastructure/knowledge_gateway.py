from __future__ import annotations

import httpx

from app.domain.models import RetrievedChunk


class NullKnowledgeGateway:
    """No-op retrieval used when RAG is disabled or Qdrant is unreachable.

    Returns an empty corpus so the agent degrades to ungrounded answers instead of
    hard-failing the demo (spec_rag.md §5.2).
    """

    async def retrieve(
        self,
        query: str,
        correlation_id: str,
        *,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        return []


class QdrantKnowledgeGateway:
    """Flat vector retrieval over Qdrant (spec_rag.md §5.2).

    Embeds the query through the OpenAI-compatible ``/v1/embeddings`` endpoint (served by
    Ollama in the deployed engine split), searches the ``vcore_operations_ko`` collection,
    and maps each Qdrant hit's payload back to a ``RetrievedChunk``. Any transport error is
    swallowed to an empty result so a degraded vector store never breaks a chat turn.
    """

    def __init__(
        self,
        qdrant_url: str,
        collection: str,
        embed_base_url: str,
        embed_model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self._collection = collection
        self._embed_base_url = embed_base_url.rstrip("/")
        self._embed_model = embed_model
        self._timeout_seconds = timeout_seconds

    async def retrieve(
        self,
        query: str,
        correlation_id: str,
        *,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                vector = await self._embed(client, query, correlation_id)
                if not vector:
                    return []
                hits = await self._search(client, vector, top_k, filters)
        except (httpx.HTTPError, ValueError, KeyError):
            return []
        return [self._to_chunk(hit) for hit in hits]

    async def _embed(
        self, client: httpx.AsyncClient, query: str, correlation_id: str
    ) -> list[float]:
        response = await client.post(
            f"{self._embed_base_url}/v1/embeddings",
            json={"model": self._embed_model, "input": query},
            headers={"x-correlation-id": correlation_id},
        )
        response.raise_for_status()
        data = response.json().get("data") or []
        if not data:
            return []
        return data[0].get("embedding") or []

    async def _search(
        self,
        client: httpx.AsyncClient,
        vector: list[float],
        top_k: int,
        filters: dict[str, str] | None,
    ) -> list[dict]:
        body: dict = {"vector": vector, "limit": top_k, "with_payload": True}
        if filters:
            body["filter"] = {
                "must": [
                    {"key": key, "match": {"value": value}}
                    for key, value in filters.items()
                ]
            }
        response = await client.post(
            f"{self._qdrant_url}/collections/{self._collection}/points/search",
            json=body,
        )
        response.raise_for_status()
        return response.json().get("result") or []

    def _to_chunk(self, hit: dict) -> RetrievedChunk:
        payload = hit.get("payload") or {}
        return RetrievedChunk(
            document_id=str(payload.get("document_id", hit.get("id", ""))),
            title=str(payload.get("title", "")),
            text=str(payload.get("text", "")),
            score=float(hit.get("score", 0.0)),
            source=str(payload.get("source", "unknown")),
            category=str(payload.get("category", "unknown")),
        )
