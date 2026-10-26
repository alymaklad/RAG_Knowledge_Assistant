import httpx


async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_ready_reports_every_dependency(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/ready")
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["checks"] == {"postgres": "ok", "qdrant": "ok", "embedder": "ok"}
