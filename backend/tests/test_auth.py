import httpx

from tests.helpers import register


async def test_register_login_me_logout(client: httpx.AsyncClient) -> None:
    user = await register(client, "alice")
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == user["email"]

    await client.post("/api/auth/logout")
    client.cookies.clear()
    assert (await client.get("/api/auth/me")).status_code == 401

    resp = await client.post(
        "/api/auth/login", json={"email": user["email"], "password": "correct-horse-battery"}
    )
    assert resp.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_login_rejects_bad_password(client: httpx.AsyncClient) -> None:
    user = await register(client, "bob")
    client.cookies.clear()
    resp = await client.post(
        "/api/auth/login", json={"email": user["email"], "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_duplicate_email_rejected(client: httpx.AsyncClient) -> None:
    user = await register(client, "carol")
    resp = await client.post(
        "/api/auth/register",
        json={"email": user["email"].upper(), "password": "another-password"},
    )
    assert resp.status_code == 409


async def test_bearer_token_auth(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/register",
        json={"email": "bearer@example.edu", "password": "correct-horse-battery"},
    )
    token = resp.json()["access_token"]
    client.cookies.clear()
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


async def test_cookie_auth_requires_csrf_on_writes(client: httpx.AsyncClient) -> None:
    await register(client, "dave")
    del client.headers["X-CSRF-Token"]
    resp = await client.post("/api/courses", json={"name": "No CSRF"})
    assert resp.status_code == 403


async def test_refresh_rotates_access_cookie(client: httpx.AsyncClient) -> None:
    await register(client, "erin")
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
