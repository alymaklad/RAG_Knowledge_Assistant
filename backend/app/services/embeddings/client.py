"""Clients for the BGE-m3 embedder service.

`HttpEmbeddingClient` talks to the `embedder` container. `HashEmbeddingClient` is a deterministic,
dependency-free stand-in (bag-of-words hashing) used by tests and offline development.
"""

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(slots=True)
class SparseVec:
    indices: list[int]
    values: list[float]


@dataclass(slots=True)
class Embeddings:
    dense: list[list[float]]
    sparse: list[SparseVec]


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str], *, sparse: bool = True) -> Embeddings: ...

    async def rerank(self, query: str, documents: list[str]) -> list[float]: ...

    async def health(self) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


class HttpEmbeddingClient:
    def __init__(self, base_url: str, batch_size: int = 32, timeout: float = 300.0) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._batch_size = batch_size

    async def embed(self, texts: list[str], *, sparse: bool = True) -> Embeddings:
        dense: list[list[float]] = []
        sparse_out: list[SparseVec] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            resp = await self._http.post("/embed", json={"texts": batch, "sparse": sparse})
            resp.raise_for_status()
            data = resp.json()
            dense.extend(data["dense"])
            sparse_out.extend(SparseVec(**s) for s in data.get("sparse") or [])
        return Embeddings(dense=dense, sparse=sparse_out)

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        resp = await self._http.post("/rerank", json={"query": query, "documents": documents})
        resp.raise_for_status()
        return list(resp.json()["scores"])

    async def health(self) -> dict[str, Any]:
        resp = await self._http.get("/health", timeout=5.0)
        resp.raise_for_status()
        return dict(resp.json())

    async def aclose(self) -> None:
        await self._http.aclose()


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_SPARSE_VOCAB = 250_002  # BGE-m3 (XLM-R) vocabulary size


def _hash(value: str, mod: int) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % mod


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def hash_dense(text: str, dim: int) -> list[float]:
    toks = _tokens(text)
    features = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]
    vec = [0.0] * dim
    for feature in features:
        h = _hash(feature, 2 * dim)
        vec[h // 2] += 1.0 if h % 2 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def hash_sparse(text: str) -> SparseVec:
    weights: dict[int, float] = {}
    for tok, count in Counter(_tokens(text)).items():
        idx = _hash(tok, _SPARSE_VOCAB)
        weights[idx] = max(weights.get(idx, 0.0), 0.1 + 0.1 * math.log1p(count))
    return SparseVec(indices=list(weights), values=list(weights.values()))


def hash_rerank(query: str, document: str) -> float:
    q = set(_tokens(query))
    if not q:
        return 0.0
    return len(q & set(_tokens(document))) / len(q)


class HashEmbeddingClient:
    def __init__(self, dim: int) -> None:
        self._dim = dim

    async def embed(self, texts: list[str], *, sparse: bool = True) -> Embeddings:
        return Embeddings(
            dense=[hash_dense(t, self._dim) for t in texts],
            sparse=[hash_sparse(t) for t in texts] if sparse else [],
        )

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [hash_rerank(query, d) for d in documents]

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "backend": "hash", "dim": self._dim}

    async def aclose(self) -> None:
        return None
