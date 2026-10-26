"""Smoke tests for the embedder API using the hash backend (no model download).

Run: EMBEDDER_BACKEND=hash pytest embedder/test_main.py
"""

import os

os.environ["EMBEDDER_BACKEND"] = "hash"

from fastapi.testclient import TestClient  # noqa: E402

from main import DIM, app  # noqa: E402

client = TestClient(app)


def test_health() -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["backend"] == "hash"


def test_embed_returns_dense_and_sparse() -> None:
    body = client.post("/embed", json={"texts": ["hello world", "tcp handshake"]}).json()
    assert len(body["dense"]) == 2
    assert len(body["dense"][0]) == DIM
    assert len(body["sparse"]) == 2
    assert len(body["sparse"][0]["indices"]) == len(body["sparse"][0]["values"]) > 0


def test_embed_dense_only() -> None:
    body = client.post("/embed", json={"texts": ["x"], "sparse": False}).json()
    assert body["sparse"] is None


def test_rerank_orders_by_overlap() -> None:
    scores = client.post(
        "/rerank", json={"query": "tcp handshake", "documents": ["udp", "the tcp handshake"]}
    ).json()["scores"]
    assert scores[1] > scores[0]
