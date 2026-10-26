from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
from fastapi import FastAPI

from app.services.llm.client import FakeLLM
from tests.helpers import create_course, make_pdf, parse_sse, register, upload

BAYES_PDF = make_pdf(
    [
        (
            "Bayesian Networks",
            "A Bayesian network is a directed acyclic graph whose nodes are random variables. "
            "Each node has a conditional probability table given its parents.",
        ),
        (
            "Markov Blanket",
            "The Markov blanket of a node consists of its parents, its children, and the other "
            "parents of its children. Given its Markov blanket, a node is conditionally "
            "independent of every other node in the network.",
        ),
    ]
)

ClientFactory = Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]


async def test_upload_indexes_pdf_with_pages_and_sections(client: httpx.AsyncClient) -> None:
    await register(client)
    course_id = await create_course(client)
    doc = await upload(client, course_id, "week6.pdf", BAYES_PDF)

    resp = await client.get(f"/api/courses/{course_id}/documents/{doc['id']}")
    body = resp.json()
    assert body["status"] == "indexed", body
    assert body["page_count"] == 2
    assert body["chunk_count"] >= 2

    chunks = (await client.get(f"/api/courses/{course_id}/documents/{doc['id']}/chunks")).json()
    assert {c["page_num"] for c in chunks} == {1, 2}
    assert "Markov Blanket" in {c["section_header"] for c in chunks}


async def test_upload_rejects_mismatched_and_unsafe_files(client: httpx.AsyncClient) -> None:
    await register(client)
    course_id = await create_course(client)
    url = f"/api/courses/{course_id}/documents"

    resp = await client.post(url, files={"file": ("notes.pdf", b"just some plain text here")})
    assert resp.status_code == 400  # extension says PDF, content is text

    resp = await client.post(url, files={"file": ("x.exe", b"MZ\x90\x00\x03" + b"\x00" * 64)})
    assert resp.status_code == 400

    scripted = BAYES_PDF.replace(b"%%EOF", b"/JavaScript (app.alert(1))\n%%EOF")
    resp = await client.post(url, files={"file": ("evil.pdf", scripted)})
    assert resp.status_code == 400


async def test_text_upload_and_delete_removes_chunks(client: httpx.AsyncClient) -> None:
    await register(client)
    course_id = await create_course(client)
    doc = await upload(
        client, course_id, "notes.md", b"# TCP\nThe TCP three-way handshake uses SYN, SYN-ACK, ACK."
    )
    assert (await client.get(f"/api/courses/{course_id}/documents/{doc['id']}")).json()[
        "status"
    ] == "indexed"

    resp = await client.delete(f"/api/courses/{course_id}/documents/{doc['id']}")
    assert resp.status_code == 204
    docs = (await client.get(f"/api/courses/{course_id}/documents")).json()
    assert docs == []


async def test_chat_streams_grounded_answer_with_sources(
    client: httpx.AsyncClient, fake_llm: FakeLLM
) -> None:
    await register(client)
    course_id = await create_course(client)
    await upload(client, course_id, "week6.pdf", BAYES_PDF)

    resp = await client.post(
        "/api/chat", json={"course_id": course_id, "message": "What is a Markov blanket?"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "session" and kinds[1] == "sources" and kinds[-1] == "done"

    sources = events[1][1]
    assert sources and sources[0]["document_name"] == "week6.pdf"
    assert "parents, its children" in sources[0]["text"]
    answer = "".join(d["t"] for e, d in events if e == "token")
    assert "[Source 1]" in answer

    # The prompt fences the retrieved context and includes the question.
    prompt = fake_llm.calls[-1][-1]["content"]
    assert prompt.startswith("<context>") and "Question: What is a Markov blanket?" in prompt

    session_id = events[0][1]["id"]
    messages = (await client.get(f"/api/sessions/{session_id}/messages")).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["source_chunks"][0]["document_name"] == "week6.pdf"


async def test_chat_without_documents_returns_not_found_without_llm_call(
    client: httpx.AsyncClient, fake_llm: FakeLLM
) -> None:
    await register(client)
    course_id = await create_course(client)
    resp = await client.post("/api/chat", json={"course_id": course_id, "message": "Anything?"})
    events = parse_sse(resp.text)
    assert events[1] == ("sources", [])
    assert "could not find" in "".join(d["t"] for e, d in events if e == "token")
    assert fake_llm.calls == []


async def test_multi_turn_sends_history(client: httpx.AsyncClient, fake_llm: FakeLLM) -> None:
    await register(client)
    course_id = await create_course(client)
    await upload(client, course_id, "week6.pdf", BAYES_PDF)
    first = parse_sse(
        (
            await client.post(
                "/api/chat", json={"course_id": course_id, "message": "What is a Bayesian network?"}
            )
        ).text
    )
    session_id = first[0][1]["id"]
    await client.post(
        "/api/chat",
        json={"course_id": course_id, "session_id": session_id, "message": "And its blanket?"},
    )
    roles = [m["role"] for m in fake_llm.calls[-1]]
    assert roles == ["system", "user", "assistant", "user"]


async def test_course_isolation(make_client: ClientFactory) -> None:
    async with make_client() as alice, make_client() as mallory:
        await register(alice, "alice")
        await register(mallory, "mallory")
        course_id = await create_course(alice, "Alice's course")
        doc = await upload(alice, course_id, "week6.pdf", BAYES_PDF)
        chat = parse_sse(
            (
                await alice.post(
                    "/api/chat", json={"course_id": course_id, "message": "Markov blanket?"}
                )
            ).text
        )
        session_id = chat[0][1]["id"]

        assert (await mallory.get(f"/api/courses/{course_id}")).status_code == 404
        assert (await mallory.get(f"/api/courses/{course_id}/documents")).status_code == 404
        assert (
            await mallory.get(f"/api/courses/{course_id}/documents/{doc['id']}/chunks")
        ).status_code == 404
        assert (await mallory.get(f"/api/sessions/{session_id}/messages")).status_code == 404
        resp = await mallory.post("/api/chat", json={"course_id": course_id, "message": "leak?"})
        assert resp.status_code == 404
        # Mallory's own course can't see Alice's chunks either.
        own = await create_course(mallory, "Mallory's course")
        events = parse_sse(
            (await mallory.post("/api/chat", json={"course_id": own, "message": "Markov"})).text
        )
        assert events[1] == ("sources", [])


async def test_students_can_chat_but_not_upload(make_client: ClientFactory) -> None:
    async with make_client() as teacher, make_client() as student:
        await register(teacher, "teacher")
        s = await register(student, "student")
        course_id = await create_course(teacher)
        resp = await teacher.post(
            f"/api/courses/{course_id}/members", json={"email": s["email"], "role": "student"}
        )
        assert resp.status_code == 201
        assert (await student.get(f"/api/courses/{course_id}")).json()["role"] == "student"
        resp = await student.post(
            f"/api/courses/{course_id}/documents", files={"file": ("a.txt", b"hello there world")}
        )
        assert resp.status_code == 403
        resp = await student.post("/api/chat", json={"course_id": course_id, "message": "hi"})
        assert resp.status_code == 200


async def test_original_file_is_served_to_members_only(make_client: ClientFactory) -> None:
    async with make_client() as owner, make_client() as other:
        await register(owner, "owner")
        await register(other, "other")
        course_id = await create_course(owner)
        doc = await upload(owner, course_id, "week6.pdf", BAYES_PDF)
        url = f"/api/courses/{course_id}/documents/{doc['id']}/file"
        resp = await owner.get(url)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == BAYES_PDF
        assert (await other.get(url)).status_code == 404


async def test_rerank_threshold_abstains_without_llm_call(
    app: FastAPI, client: httpx.AsyncClient, fake_llm: FakeLLM
) -> None:
    await register(client)
    course_id = await create_course(client)
    await upload(client, course_id, "week6.pdf", BAYES_PDF)
    services = app.state.services
    original = services.settings
    services.settings = original.model_copy(
        update={"rerank_enabled": True, "rerank_threshold": 0.5}
    )
    try:
        off_topic = parse_sse(
            (
                await client.post(
                    "/api/chat",
                    json={"course_id": course_id, "message": "Dijkstra shortest path runtime"},
                )
            ).text
        )
        assert off_topic[1] == ("sources", [])
        assert fake_llm.calls == []

        on_topic = parse_sse(
            (
                await client.post(
                    "/api/chat", json={"course_id": course_id, "message": "Markov blanket node"}
                )
            ).text
        )
        assert on_topic[1][1], "relevant passages pass the threshold"
    finally:
        services.settings = original
