"""OpenSearch-compatible retrieval backends for IntelliDocs."""

from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .embeddings import EmbeddingModel, cosine_similarity
from .models import Chunk, UserContext
from .security import AuthFilter, build_auth_filter, is_authorized

DEFAULT_LEXICAL_TOP_K = int(os.getenv("RETRIEVAL_LEXICAL_TOP_K", "50"))
DEFAULT_VECTOR_TOP_K = int(os.getenv("RETRIEVAL_VECTOR_TOP_K", "50"))
DEFAULT_FUSED_CANDIDATES = int(os.getenv("RETRIEVAL_FUSED_CANDIDATES", "80"))
DEFAULT_RERANK_MAX = int(os.getenv("RERANK_MAX_CANDIDATES", "60"))
DEFAULT_FINAL_TOP_N = int(os.getenv("FINAL_CONTEXT_CHUNKS", "8"))
DEFAULT_RRF_K = 60
DEFAULT_HNSW_M = int(os.getenv("HNSW_M", "32"))
DEFAULT_HNSW_EF_CONSTRUCTION = int(os.getenv("HNSW_EF_CONSTRUCTION", "256"))
DEFAULT_HNSW_EF_SEARCH = int(os.getenv("HNSW_EF_SEARCH", "128"))
DEFAULT_INDEX_NAME = os.getenv("OPENSEARCH_INDEX", "intellidocs-v1")

_TOKEN_RE = re.compile(r"[A-Za-z0-9\.\-:_]+")


class RetrievalBackend(Protocol):
    @property
    def chunks(self) -> list[Chunk]: ...

    def lexical_search(
        self, query: str, user: UserContext, *, top_k: int = DEFAULT_LEXICAL_TOP_K, document_names: list[str] | None = None
    ) -> list[tuple[Chunk, float]]: ...

    def vector_search(
        self,
        query_embedding: list[float],
        user: UserContext,
        *, top_k: int = DEFAULT_VECTOR_TOP_K,
        document_names: list[str] | None = None
    ) -> list[tuple[Chunk, float]]: ...
    
    def add_chunks(self, chunks: list[Chunk]) -> None: ...


@dataclass
class FusionResult:
    chunk: Chunk
    rrf_score: float
    lexical_rank: int | None = None
    vector_rank: int | None = None
    lexical_score: float = 0.0
    vector_score: float = 0.0


def build_index_mapping(*, dimension: int = 1536) -> dict[str, Any]:
    """Return the OpenSearch mapping/settings. Default 1536 is for OpenAI embeddings."""
    return {
        "settings": {
            "index.knn": True,
            "index.knn.algo_param.ef_search": DEFAULT_HNSW_EF_SEARCH,
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "1s",
        },
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "document_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "text": {"type": "text"},
                "page_number": {"type": "integer"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dimension,
                    "method": {
                        "name": "hnsw",
                        "engine": "faiss",
                        "space_type": "innerproduct",
                        "parameters": {
                            "m": DEFAULT_HNSW_M,
                            "ef_construction": DEFAULT_HNSW_EF_CONSTRUCTION,
                        },
                    },
                },
            }
        },
    }


def build_opensearch_queries(
    *,
    query_text: str,
    query_embedding: list[float],
    auth_filter: dict[str, Any] | AuthFilter,
    lexical_top_k: int = DEFAULT_LEXICAL_TOP_K,
    vector_top_k: int = DEFAULT_VECTOR_TOP_K,
) -> dict[str, dict[str, Any]]:
    auth_body = auth_filter.to_opensearch_filter() if isinstance(auth_filter, AuthFilter) else auth_filter
    auth_bool = auth_body["bool"]
    auth_filters = list(auth_bool.get("filter", []))
    auth_must_not = list(auth_bool.get("must_not", []))

    lexical = {
        "size": lexical_top_k,
        "query": {
            "bool": {
                "filter": auth_filters,
                "must_not": auth_must_not,
                "must": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": ["document_name^5", "text^2"],
                            "type": "best_fields",
                        }
                    }
                ],
            }
        },
    }

    vector = {
        "size": vector_top_k,
        "query": {
            "bool": {
                "filter": auth_filters,
                "must_not": auth_must_not,
                "must": [
                    {
                        "knn": {
                            "embedding": {
                                "vector": query_embedding,
                                "k": vector_top_k,
                                "method_parameters": {"ef_search": DEFAULT_HNSW_EF_SEARCH},
                            }
                        }
                    }
                ],
            }
        },
    }
    return {"lexical": lexical, "vector": vector}


class InMemoryOpenSearchBackend:
    def __init__(self, chunks: list[Chunk], *, embedder: EmbeddingModel | None = None) -> None:
        self._embedder = embedder or EmbeddingModel()
        self._chunks = list(chunks)
        self._ensure_chunk_embeddings(self._chunks)

    def _ensure_chunk_embeddings(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            if not chunk.embedding:
                chunk.embedding = self._embedder.embed(_embedding_text(chunk))

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks)

    def add_chunks(self, chunks: list[Chunk]) -> None:
        self._ensure_chunk_embeddings(chunks)
        self._chunks.extend(chunks)

    def _authorized(self, user: UserContext) -> list[Chunk]:
        auth = build_auth_filter(user)
        return [c for c in self._chunks if is_authorized(c, user, auth=auth)]

    def lexical_search(
        self, query: str, user: UserContext, *, top_k: int = DEFAULT_LEXICAL_TOP_K, document_names: list[str] | None = None
    ) -> list[tuple[Chunk, float]]:
        query_tokens = _tokens(query)
        scored: list[tuple[Chunk, float]] = []
        for chunk in self._authorized(user):
            if document_names is not None and chunk.document_name not in document_names:
                continue
            score = _lexical_score(query_tokens, chunk)
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda row: (row[1], row[0].chunk_id), reverse=True)
        return scored[:top_k]

    def vector_search(
        self,
        query_embedding: list[float],
        user: UserContext,
        *,
        top_k: int = DEFAULT_VECTOR_TOP_K,
        document_names: list[str] | None = None
    ) -> list[tuple[Chunk, float]]:
        scored: list[tuple[Chunk, float]] = []
        for chunk in self._authorized(user):
            if document_names is not None and chunk.document_name not in document_names:
                continue
            sim = cosine_similarity(query_embedding, chunk.embedding)
            if sim > 0:
                scored.append((chunk, sim))
        scored.sort(key=lambda row: (row[1], row[0].chunk_id), reverse=True)
        return scored[:top_k]


class OpenSearchBackend:
    def _ensure_chunk_embeddings(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            if not chunk.embedding:
                chunk.embedding = self._embedder.embed(_embedding_text(chunk))

    def __init__(
        self,
        chunks: list[Chunk],
        *,
        embedder: EmbeddingModel | None = None,
        url: str | None = None,
        index_name: str = DEFAULT_INDEX_NAME,
        recreate_index: bool = False,
        timeout_seconds: int = 30,
    ) -> None:
        try:
            from opensearchpy import OpenSearch, helpers
        except ModuleNotFoundError as exc:
            raise RuntimeError("opensearch-py is required for OpenSearchBackend") from exc

        self._OpenSearch = OpenSearch
        self._helpers = helpers
        self._embedder = embedder or EmbeddingModel()
        self._chunks = list(chunks)
        self._index_name = index_name
        self._client = self._build_client(url=url, timeout_seconds=timeout_seconds)
        self._chunk_by_id = {chunk.chunk_id: chunk for chunk in self._chunks}

        self.wait_until_ready(timeout_seconds=timeout_seconds)
        if recreate_index and self._client.indices.exists(index=self._index_name):
            self._client.indices.delete(index=self._index_name)

        index_exists = self._client.indices.exists(index=self._index_name)
        if index_exists and self._index_has_documents() and not chunks:
            return

        self._ensure_chunk_embeddings(self._chunks)

        if not index_exists:
            dim = getattr(self._embedder, "dimension", 1536)
            self._client.indices.create(
                index=self._index_name,
                body=build_index_mapping(dimension=dim),
            )
        if self._chunks:
            self.index_chunks(self._chunks)

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks)
        
    def add_chunks(self, chunks: list[Chunk]) -> None:
        self._ensure_chunk_embeddings(chunks)
        self._chunks.extend(chunks)
        for chunk in chunks:
            self._chunk_by_id[chunk.chunk_id] = chunk
        self.index_chunks(chunks)

    @property
    def client(self):
        return self._client

    @property
    def index_name(self) -> str:
        return self._index_name

    def _index_has_documents(self) -> bool:
        try:
            result = self._client.count(index=self._index_name)
            return int(result.get("count", 0)) > 0
        except Exception:
            return False

    def _build_client(self, *, url: str | None, timeout_seconds: int):
        if url:
            return self._OpenSearch(hosts=[url], timeout=timeout_seconds)

        host = os.getenv("OPENSEARCH_HOST", "localhost")
        port = int(os.getenv("OPENSEARCH_PORT", "9200"))
        use_ssl = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
        verify_certs = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
        username = os.getenv("OPENSEARCH_USERNAME") or None
        password = os.getenv("OPENSEARCH_PASSWORD") or None
        params: dict[str, Any] = {
            "hosts": [{"host": host, "port": port}],
            "use_ssl": use_ssl,
            "verify_certs": verify_certs,
            "timeout": timeout_seconds,
        }
        if username and password:
            params["http_auth"] = (username, password)
        return self._OpenSearch(**params)

    def wait_until_ready(self, *, timeout_seconds: int = 30) -> None:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                if self._client.ping():
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(1)
        raise RuntimeError(f"OpenSearch not reachable for index {self._index_name}: {last_error}")

    def index_chunks(self, chunks: list[Chunk]) -> None:
        actions = []
        for chunk in chunks:
            actions.append(
                {
                    "_op_type": "index",
                    "_index": self._index_name,
                    "_id": chunk.chunk_id,
                    "_source": chunk.to_index_doc(),
                }
            )
        if actions:
            self._helpers.bulk(self._client, actions, refresh=True)

    def lexical_search(
        self, query: str, user: UserContext, *, top_k: int = DEFAULT_LEXICAL_TOP_K
    ) -> list[tuple[Chunk, float]]:
        auth = build_auth_filter(user)
        body = build_opensearch_queries(
            query_text=query,
            query_embedding=self._embedder.embed(query),
            auth_filter=auth,
            lexical_top_k=top_k,
        )["lexical"]
        results = self._client.search(index=self._index_name, body=body)
        return self._hits_to_chunks(results)

    def vector_search(
        self,
        query_embedding: list[float],
        user: UserContext,
        *,
        top_k: int = DEFAULT_VECTOR_TOP_K,
    ) -> list[tuple[Chunk, float]]:
        auth = build_auth_filter(user)
        body = build_opensearch_queries(
            query_text="",
            query_embedding=query_embedding,
            auth_filter=auth,
            vector_top_k=top_k,
        )["vector"]
        results = self._client.search(index=self._index_name, body=body)
        return self._hits_to_chunks(results)

    def _hits_to_chunks(self, results: dict[str, Any]) -> list[tuple[Chunk, float]]:
        scored: list[tuple[Chunk, float]] = []
        for hit in results.get("hits", {}).get("hits", []):
            chunk = self._chunk_by_id.get(hit.get("_id"))
            if chunk is not None:
                scored.append((chunk, float(hit.get("_score") or 0.0)))
        return scored


def reciprocal_rank_fusion(
    ranked_lists: list[list[Chunk]] | list[list[tuple[Chunk, float]]],
    *,
    rank_constant: int = DEFAULT_RRF_K,
) -> list[FusionResult]:
    by_id: dict[str, FusionResult] = {}
    for list_idx, ranked in enumerate(ranked_lists):
        for rank, item in enumerate(ranked, start=1):
            chunk = item[0] if isinstance(item, tuple) else item
            source_score = float(item[1]) if isinstance(item, tuple) else 0.0
            existing = by_id.get(chunk.chunk_id)
            if existing is None:
                existing = FusionResult(chunk=chunk, rrf_score=0.0)
                by_id[chunk.chunk_id] = existing
            existing.rrf_score += 1.0 / (rank_constant + rank)
            if list_idx == 0:
                existing.lexical_rank = rank
                existing.lexical_score = source_score
            elif list_idx == 1:
                existing.vector_rank = rank
                existing.vector_score = source_score
    return sorted(by_id.values(), key=lambda r: (r.rrf_score, r.chunk.chunk_id), reverse=True)


def take_candidates(fused: list[FusionResult], *, limit: int = DEFAULT_FUSED_CANDIDATES) -> list[FusionResult]:
    return fused[:limit]


def rerank(
    query: str,
    candidates: list[FusionResult],
    *,
    max_candidates: int = DEFAULT_RERANK_MAX,
) -> list[FusionResult]:
    query_tokens = _tokens(query)
    reranked = list(candidates[:max_candidates])
    for row in reranked:
        lexical_bonus = _lexical_score(query_tokens, row.chunk) * 0.01
        row.rrf_score += lexical_bonus
    return sorted(reranked, key=lambda r: (r.rrf_score, r.chunk.chunk_id), reverse=True)


def take_with_complete_citations(
    reranked: list[FusionResult], *, limit: int = DEFAULT_FINAL_TOP_N
) -> list[Chunk]:
    complete_rows: list[FusionResult] = []
    for row in reranked:
        chunk = row.chunk
        if not (chunk.document_name and chunk.document_id and chunk.page_number is not None):
            continue
        complete_rows.append(row)

    merged_rows = complete_rows
    merged_rows.sort(key=lambda row: (row.rrf_score, row.chunk.chunk_id), reverse=True)
    return [row.chunk for row in merged_rows[:limit]]


def hybrid_retrieve(
    *,
    query: str,
    user: UserContext,
    backend: RetrievalBackend,
    embedder: EmbeddingModel,
    lexical_top_k: int = DEFAULT_LEXICAL_TOP_K,
    vector_top_k: int = DEFAULT_VECTOR_TOP_K,
    fused_candidates: int = DEFAULT_FUSED_CANDIDATES,
    rerank_max: int = DEFAULT_RERANK_MAX,
    final_top_n: int = DEFAULT_FINAL_TOP_N,
    reranker: Any | None = None,
    document_names: list[str] | None = None
) -> tuple[list[Chunk], dict[str, Any]]:
    query_embedding = embedder.embed_query(query) if hasattr(embedder, "embed_query") else embedder.embed(query)
    lexical_hits = backend.lexical_search(query, user, top_k=lexical_top_k, document_names=document_names)
    vector_hits = backend.vector_search(query_embedding, user, top_k=vector_top_k, document_names=document_names)
    fused = reciprocal_rank_fusion([lexical_hits, vector_hits])
    candidates = take_candidates(fused, limit=fused_candidates)
    
    if reranker is None:
        reranked = rerank(query, candidates, max_candidates=rerank_max)
        reranker_name = "deterministic"
    else:
        reranked = reranker(query, candidates[:rerank_max]) if callable(reranker) else reranker.rerank(query, candidates[:rerank_max])
        reranker_name = getattr(reranker, "model_id", reranker.__class__.__name__)
        
    final = take_with_complete_citations(reranked, limit=final_top_n)

    forbidden = [c for c in final if not is_authorized(c, user)]
    if forbidden:
        raise AssertionError(f"RBAC leakage in final context: {[c.chunk_id for c in forbidden]}")

    debug = {
        "lexical_chunk_ids": [c.chunk_id for c, _ in lexical_hits],
        "vector_chunk_ids": [c.chunk_id for c, _ in vector_hits],
        "fused_chunk_ids": [r.chunk.chunk_id for r in fused[:fused_candidates]],
        "reranked_chunk_ids": [r.chunk.chunk_id for r in reranked],
        "final_chunk_ids": [c.chunk_id for c in final],
        "reranker": reranker_name,
    }
    return final, debug


def _tokens(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text)]


def _embedding_text(chunk: Chunk) -> str:
    return f"{chunk.document_name} Page {chunk.page_number}\n{chunk.text}"


def _lexical_score(query_tokens: list[str], chunk: Chunk) -> float:
    if not query_tokens:
        return 0.0
    fields = {
        "document_name": (chunk.document_name, 5.0),
        "text": (chunk.text, 2.0),
    }
    score = 0.0
    for token in query_tokens:
        for value, weight in fields.values():
            low = value.lower()
            if token == low:
                score += weight * 2.0
            elif token in low:
                score += weight
    if score == 0:
        return 0.0
    return score / math.sqrt(len(query_tokens))
