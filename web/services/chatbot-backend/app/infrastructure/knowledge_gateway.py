from __future__ import annotations

import json
import math
import re

import httpx

from app.application.ports import ControlServerClient, SessionRepository
from app.domain.models import RetrievedChunk
from app.domain.ontology import GraphRagRetriever


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


class HybridGraphKnowledgeGateway:
    """PB hybrid retriever: graph path for relational questions, vector path for free text."""

    def __init__(
        self,
        vector_gateway: QdrantKnowledgeGateway,
        control_client: ControlServerClient,
        repository: SessionRepository,
        graph_retriever: GraphRagRetriever | None = None,
    ) -> None:
        self._vector_gateway = vector_gateway
        self._control_client = control_client
        self._repository = repository
        self._graph = graph_retriever or GraphRagRetriever()

    async def retrieve(
        self,
        query: str,
        correlation_id: str,
        *,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        if self._graph.is_relational_query(query):
            graph_chunks = await self._retrieve_graph(query, correlation_id, top_k=top_k)
            if graph_chunks:
                return graph_chunks
        return await self._vector_gateway.retrieve(
            query, correlation_id, top_k=top_k, filters=filters
        )

    async def _retrieve_graph(
        self,
        query: str,
        correlation_id: str,
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        try:
            stations = await self._control_client.list_stations(correlation_id)
            runs = await self._repository.list_runs()
        except Exception:
            return []
        return self._graph.retrieve(query, stations, runs, top_k=top_k)


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
        qdrant_api_key: str | None = None,
        qdrant_fallback_url: str | None = None,
        timeout_seconds: float = 30.0,
        fetch_k: int = 10,
        rerank_mode: str = "lexical",
        min_score: float = 0.0,
        rerank_base_url: str | None = None,
        rerank_model: str | None = None,
    ) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self._qdrant_api_key = qdrant_api_key
        self._qdrant_fallback_url = (qdrant_fallback_url or "").rstrip("/")
        self._collection = collection
        self._embed_base_url = embed_base_url.rstrip("/")
        self._embed_model = embed_model
        self._timeout_seconds = timeout_seconds
        self._fetch_k = max(1, fetch_k)
        self._rerank_mode = rerank_mode.lower().strip()
        self._min_score = min_score
        self._rerank_base_url = (rerank_base_url or "").rstrip("/")
        self._rerank_model = rerank_model or ""

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
                hits = await self._search(client, vector, max(top_k, self._fetch_k), filters)
                chunks = [self._to_chunk(hit) for hit in hits]
                chunks = [
                    chunk for chunk in chunks if (chunk.vector_score or chunk.score) >= self._min_score
                ]
                chunks = await self._rerank(client, query, chunks, top_k, correlation_id)
        except (httpx.HTTPError, ValueError, KeyError):
            return []
        return chunks[:top_k]

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
        try:
            return await self._search_endpoint(
                client, self._qdrant_url, body, api_key=self._qdrant_api_key
            )
        except httpx.HTTPError:
            if not self._qdrant_fallback_url:
                raise
            return await self._search_endpoint(client, self._qdrant_fallback_url, body)

    async def _search_endpoint(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        body: dict,
        *,
        api_key: str | None = None,
    ) -> list[dict]:
        headers = {"api-key": api_key} if api_key else None
        response = await client.post(
            f"{base_url}/collections/{self._collection}/points/search",
            json=body,
            headers=headers,
        )
        response.raise_for_status()
        return response.json().get("result") or []

    def _to_chunk(self, hit: dict) -> RetrievedChunk:
        payload = hit.get("payload") or {}
        vector_score = float(hit.get("score", 0.0))
        return RetrievedChunk(
            document_id=str(payload.get("document_id", hit.get("id", ""))),
            title=str(payload.get("title", "")),
            text=str(payload.get("text", "")),
            score=vector_score,
            source=str(payload.get("source", "unknown")),
            category=str(payload.get("category", "unknown")),
            vector_score=vector_score,
        )

    async def _rerank(
        self,
        client: httpx.AsyncClient,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
        correlation_id: str,
    ) -> list[RetrievedChunk]:
        if not chunks or self._rerank_mode in {"", "off", "none", "vector"}:
            return chunks
        if self._rerank_mode == "llm" and self._rerank_base_url and self._rerank_model:
            try:
                return await self._llm_rerank(client, query, chunks, top_k, correlation_id)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        return lexical_rerank(query, chunks)

    async def _llm_rerank(
        self,
        client: httpx.AsyncClient,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
        correlation_id: str,
    ) -> list[RetrievedChunk]:
        candidates = [
            {
                "id": str(index),
                "document_id": chunk.document_id,
                "title": chunk.title,
                "text": chunk.text[:700],
            }
            for index, chunk in enumerate(chunks)
        ]
        prompt = (
            "Rank the candidate knowledge chunks for answering the query. "
            "Return only JSON: {\"ranked_ids\": [\"0\", \"1\"]}. "
            "Use only candidate ids, most relevant first.\n\n"
            f"Query: {query}\n\nCandidates:\n{json.dumps(candidates, ensure_ascii=False)}"
        )
        response = await client.post(
            f"{self._rerank_base_url}/v1/chat/completions",
            json={
                "model": self._rerank_model,
                "stream": False,
                "temperature": 0.0,
                "max_tokens": 128,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a strict search-result reranker.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            headers={"x-correlation-id": correlation_id},
        )
        response.raise_for_status()
        choices = response.json().get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        ranked_ids = json.loads(content).get("ranked_ids") or []
        by_id = {str(index): chunk for index, chunk in enumerate(chunks)}
        reranked: list[RetrievedChunk] = []
        seen: set[str] = set()
        for rank, candidate_id in enumerate(ranked_ids):
            key = str(candidate_id)
            chunk = by_id.get(key)
            if chunk is None or key in seen:
                continue
            seen.add(key)
            score = float(len(chunks) - rank) / max(len(chunks), 1)
            reranked.append(chunk.model_copy(update={"score": score, "rerank_score": score}))
        reranked.extend(chunk for key, chunk in by_id.items() if key not in seen)
        return reranked[:top_k]


def lexical_rerank(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Offline-safe PA.3 reranker: fuse vector score with query/document token overlap."""

    query_terms = _tokenize(query)
    if not query_terms:
        return chunks
    max_vector = max((chunk.vector_score or chunk.score for chunk in chunks), default=1.0) or 1.0
    reranked: list[RetrievedChunk] = []
    for chunk in chunks:
        body_terms = _tokenize(chunk.text)
        title_terms = _tokenize(chunk.title)
        overlap = len(query_terms & body_terms) + (2 * len(query_terms & title_terms))
        lexical_score = overlap / math.sqrt(max(len(query_terms), 1) * max(len(body_terms | title_terms), 1))
        vector_component = (chunk.vector_score or chunk.score) / max_vector
        score = (0.9 * vector_component) + (0.1 * lexical_score)
        reranked.append(chunk.model_copy(update={"score": score, "rerank_score": lexical_score}))
    return sorted(reranked, key=lambda chunk: chunk.score, reverse=True)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[0-9A-Za-z\uac00-\ud7a3_]+", text.lower())
    stopwords = {
        "a",
        "about",
        "and",
        "does",
        "for",
        "how",
        "is",
        "of",
        "say",
        "should",
        "the",
        "what",
        "when",
        "which",
        "with",
    }
    return {token for token in tokens if len(token) > 1 and token not in stopwords}
