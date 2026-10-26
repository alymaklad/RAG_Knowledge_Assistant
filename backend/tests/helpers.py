import json
import uuid
from typing import Any

import httpx
import pymupdf


async def register(client: httpx.AsyncClient, name: str = "student") -> dict[str, Any]:
    """Register a fresh user; the client keeps the auth cookies and sends the CSRF header."""
    email = f"{name}-{uuid.uuid4().hex[:8]}@example.edu"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct-horse-battery", "full_name": name.title()},
    )
    assert resp.status_code == 201, resp.text
    client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
    return dict(resp.json()["user"])


async def create_course(client: httpx.AsyncClient, name: str = "Probabilistic AI") -> str:
    resp = await client.post("/api/courses", json={"name": name, "description": "test"})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def make_pdf(pages: list[tuple[str, str]]) -> bytes:
    """Build a PDF where each page has a large-font heading and body text."""
    doc = pymupdf.open()
    for heading, body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), heading, fontsize=20)
        page.insert_textbox(pymupdf.Rect(72, 100, 540, 780), body, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return bytes(data)


async def upload(
    client: httpx.AsyncClient, course_id: str, filename: str, data: bytes
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/courses/{course_id}/documents", files={"file": (filename, data)}
    )
    assert resp.status_code == 202, resp.text
    return dict(resp.json())


def parse_sse(raw: str) -> list[tuple[str, Any]]:
    events = []
    for block in raw.strip().split("\n\n"):
        event, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data += line[6:]
        events.append((event, json.loads(data) if data else None))
    return events
