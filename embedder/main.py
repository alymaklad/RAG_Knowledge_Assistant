"""BGE-m3 embedding + re-ranking service.

One process holds the models so the API (query embedding) and the worker (indexing) share a
single copy in memory. Two backends:

* ``bge``  - BAAI/bge-m3 dense (normalized CLS, 1024-d) + sparse lexical weights, and
             BAAI/bge-reranker-v2-m3 for cross-encoder re-ranking (loaded lazily).
* ``hash`` - deterministic bag-of-words hashing; no model download. For CI and quick local runs.
"""

import hashlib
import logging
import math
import os
import re
import threading
from collections import Counter
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

logger = logging.getLogger("embedder")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

BACKEND = os.getenv("EMBEDDER_BACKEND", "bge")
MODEL_NAME = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
MAX_LENGTH = int(os.getenv("EMBED_MAX_LENGTH", "8192"))
BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "16"))
DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
RERANK_PRELOAD = os.getenv("RERANK_PRELOAD", "true").lower() == "true"
SPARSE_VOCAB = 250_002


class RerankerUnavailable(RuntimeError):
    pass


class EmbedRequest(BaseModel):
    texts: list[str] = Field(max_length=512)
    sparse: bool = True


class SparseOut(BaseModel):
    indices: list[int]
    values: list[float]


class EmbedResponse(BaseModel):
    dense: list[list[float]]
    sparse: list[SparseOut] | None
    dim: int


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(max_length=256)


class RerankResponse(BaseModel):
    scores: list[float]


class HashBackend:
    name = "hash"
    device = "cpu"
    reranker_state = "ready"
    _token_re = re.compile(r"\w+", re.UNICODE)

    @staticmethod
    def _hash(value: str, mod: int) -> int:
        digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "little") % mod

    def _tokens(self, text: str) -> list[str]:
        return [t.lower() for t in self._token_re.findall(text)]

    def embed(self, texts: list[str], sparse: bool) -> tuple[list[list[float]], list[SparseOut]]:
        dense, sparse_out = [], []
        for text in texts:
            toks = self._tokens(text)
            vec = [0.0] * DIM
            for f in toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]:
                h = self._hash(f, 2 * DIM)
                vec[h // 2] += 1.0 if h % 2 == 0 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            dense.append([v / norm for v in vec])
            if sparse:
                weights: dict[int, float] = {}
                for tok, count in Counter(toks).items():
                    idx = self._hash(tok, SPARSE_VOCAB)
                    weights[idx] = max(weights.get(idx, 0.0), 0.1 + 0.1 * math.log1p(count))
                sparse_out.append(SparseOut(indices=list(weights), values=list(weights.values())))
        return dense, sparse_out

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        q = set(self._tokens(query))
        return [len(q & set(self._tokens(d))) / len(q) if q else 0.0 for d in documents]


class BGEM3Backend:
    """BGE-m3 inference without FlagEmbedding: dense = normalized CLS hidden state,
    sparse = ReLU(sparse_linear(hidden_states)) max-pooled per token id, special tokens dropped."""

    name = "bge"

    def __init__(self) -> None:
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        logger.info("Loading %s on %s", MODEL_NAME, self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        self.model = AutoModel.from_pretrained(MODEL_NAME, dtype=self.dtype).to(self.device).eval()
        hidden = self.model.config.hidden_size
        self.sparse_linear = torch.nn.Linear(hidden, 1)
        state = torch.load(hf_hub_download(MODEL_NAME, "sparse_linear.pt"), map_location="cpu")
        self.sparse_linear.load_state_dict(state)
        self.sparse_linear = self.sparse_linear.to(self.device, dtype=self.dtype).eval()
        tok = self.tokenizer
        self.unused_ids = {
            i
            for i in (tok.cls_token_id, tok.eos_token_id, tok.pad_token_id, tok.unk_token_id)
            if i is not None
        }
        self._reranker: Any = None
        self._rerank_tokenizer: Any = None
        self.reranker_state = "not loaded"
        # Separate locks: a slow reranker download must never block embedding.
        self._embed_lock = threading.Lock()
        self._rerank_lock = threading.Lock()
        if RERANK_PRELOAD:
            threading.Thread(target=self._load_reranker, daemon=True).start()

    def embed(self, texts: list[str], sparse: bool) -> tuple[list[list[float]], list[SparseOut]]:
        torch = self.torch
        dense_out: list[list[float]] = []
        sparse_out: list[SparseOut] = []
        with self._embed_lock, torch.inference_mode():
            for i in range(0, len(texts), BATCH_SIZE):
                batch = texts[i : i + BATCH_SIZE]
                enc = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                ).to(self.device)
                hidden = self.model(**enc).last_hidden_state
                dense = torch.nn.functional.normalize(hidden[:, 0].float(), dim=-1)
                dense_out.extend(dense.cpu().tolist())
                if not sparse:
                    continue
                weights = torch.relu(self.sparse_linear(hidden)).squeeze(-1).float().cpu()
                ids = enc["input_ids"].cpu()
                mask = enc["attention_mask"].cpu()
                for row_ids, row_w, row_m in zip(ids, weights, mask, strict=True):
                    acc: dict[int, float] = {}
                    cols = zip(row_ids.tolist(), row_w.tolist(), row_m.tolist(), strict=True)
                    for tid, w, m in cols:
                        if not m or w <= 0 or tid in self.unused_ids:
                            continue
                        if w > acc.get(tid, 0.0):
                            acc[tid] = w
                    sparse_out.append(SparseOut(indices=list(acc), values=list(acc.values())))
        return dense_out, sparse_out

    def _load_reranker(self) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        with self._rerank_lock:
            if self._reranker is not None:
                return
            self.reranker_state = "loading"
            logger.info("Loading reranker %s", RERANK_MODEL_NAME)
            try:
                tokenizer = AutoTokenizer.from_pretrained(RERANK_MODEL_NAME)
                model = AutoModelForSequenceClassification.from_pretrained(
                    RERANK_MODEL_NAME, dtype=self.dtype
                )
            except Exception:
                logger.exception("Reranker failed to load")
                self.reranker_state = "failed"
                return
            self._rerank_tokenizer = tokenizer
            self._reranker = model.to(self.device).eval()
            self.reranker_state = "ready"
            logger.info("Reranker ready")

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        torch = self.torch
        if self._reranker is None:
            raise RerankerUnavailable(self.reranker_state)
        with self._rerank_lock, torch.inference_mode():
            scores: list[float] = []
            for i in range(0, len(documents), BATCH_SIZE):
                pairs = [[query, d] for d in documents[i : i + BATCH_SIZE]]
                enc = self._rerank_tokenizer(
                    pairs, padding=True, truncation=True, max_length=1024, return_tensors="pt"
                ).to(self.device)
                logits = self._reranker(**enc).logits.view(-1).float()
                scores.extend(torch.sigmoid(logits).cpu().tolist())
            return scores


backend: HashBackend | BGEM3Backend = HashBackend() if BACKEND == "hash" else BGEM3Backend()
app = FastAPI(title="Course AI Embedder", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "backend": backend.name,
        "model": MODEL_NAME if backend.name == "bge" else None,
        "device": backend.device,
        "dim": DIM,
        "reranker": backend.reranker_state,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest) -> EmbedResponse:
    dense, sparse = await run_in_threadpool(backend.embed, req.texts, req.sparse)
    return EmbedResponse(dense=dense, sparse=sparse if req.sparse else None, dim=DIM)


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest) -> RerankResponse:
    if not req.documents:
        return RerankResponse(scores=[])
    try:
        scores = await run_in_threadpool(backend.rerank, req.query, req.documents)
    except RerankerUnavailable as exc:
        # Callers fall back to retrieval order; the model may still be downloading.
        raise HTTPException(503, f"Reranker {exc}") from exc
    return RerankResponse(scores=scores)
