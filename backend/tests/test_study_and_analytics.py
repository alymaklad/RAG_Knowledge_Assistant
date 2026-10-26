from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pymupdf

from app.services.llm.client import FakeLLM, Message
from tests.helpers import create_course, make_pdf, parse_sse, register, upload

PDF = make_pdf(
    [
        ("Slow start", "Slow start doubles the congestion window every round-trip time."),
        ("Flow control", "The receiver advertises a receive window of free buffer space."),
    ]
)

ClientFactory = Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]


def quiz_responder(messages: list[Message]) -> dict[str, Any]:
    return {
        "questions": [
            {
                "question": "How does slow start grow the congestion window?",
                "options": {"A": "Linearly", "B": "It doubles each RTT", "C": "Halves", "D": "No"},
                "correct_answer": "B",
                "explanation": "It doubles every round-trip time.",
                "difficulty": "Easy",
                "source": 1,
            },
            {
                "question": "Malformed: only two options",
                "options": {"A": "x", "B": "y"},
                "correct_answer": "A",
            },
        ]
    }


def flashcard_responder(messages: list[Message]) -> dict[str, Any]:
    return {
        "flashcards": [
            {"front": "What is the receive window?", "back": "Free buffer space.", "source": 2},
            {"front": "Bad source", "back": "Out of range source.", "source": 99},
        ]
    }


async def test_quiz_generation_saves_set_and_exports_pdf(
    client: httpx.AsyncClient, fake_llm: FakeLLM
) -> None:
    fake_llm.json_responders["multiple-choice"] = quiz_responder
    await register(client)
    course_id = await create_course(client)
    doc = await upload(client, course_id, "tcp.pdf", PDF)

    resp = await client.post(
        f"/api/courses/{course_id}/study-sets",
        json={"kind": "quiz", "count": 5, "document_id": doc["id"]},
    )
    assert resp.status_code == 201, resp.text
    quiz = resp.json()
    assert quiz["title"] == "Quiz: tcp"
    # The malformed question is dropped; the valid one keeps its source.
    assert len(quiz["items"]) == 1
    assert quiz["sources"][0]["document_name"] == "tcp.pdf"
    prompt = fake_llm.calls[-1][-1]["content"]
    assert prompt.startswith("<context>") and "Slow start doubles" in prompt

    listed = (await client.get(f"/api/courses/{course_id}/study-sets")).json()
    assert [s["id"] for s in listed] == [quiz["id"]]

    pdf = await client.get(f"/api/study-sets/{quiz['id']}/pdf")
    assert pdf.status_code == 200
    text = pymupdf.open(stream=pdf.content)[0].get_text()
    assert "How does slow start grow" in text and "Answers" in text


async def test_flashcards_from_topic_drop_invalid_sources(
    client: httpx.AsyncClient, fake_llm: FakeLLM
) -> None:
    fake_llm.json_responders["flashcards"] = flashcard_responder
    await register(client)
    course_id = await create_course(client)
    await upload(client, course_id, "tcp.pdf", PDF)
    resp = await client.post(
        f"/api/courses/{course_id}/study-sets",
        json={"kind": "flashcards", "count": 5, "topic": "receive window buffer"},
    )
    assert resp.status_code == 201, resp.text
    cards = resp.json()["items"]
    assert [c["source"] for c in cards] == [2, None]


async def test_invalid_json_is_retried_then_reported(
    client: httpx.AsyncClient, fake_llm: FakeLLM
) -> None:
    fake_llm.json_responders["multiple-choice"] = lambda m: {"nope": True}
    await register(client)
    course_id = await create_course(client)
    doc = await upload(client, course_id, "tcp.pdf", PDF)
    resp = await client.post(
        f"/api/courses/{course_id}/study-sets",
        json={"kind": "quiz", "count": 3, "document_id": doc["id"]},
    )
    assert resp.status_code == 422
    assert "invalid response" in resp.json()["detail"]
    assert len(fake_llm.calls) == 2  # one retry with the validation error


async def test_summary_is_cached_per_document(client: httpx.AsyncClient, fake_llm: FakeLLM) -> None:
    await register(client)
    course_id = await create_course(client)
    doc = await upload(client, course_id, "tcp.pdf", PDF)
    url = f"/api/courses/{course_id}/documents/{doc['id']}/summary"
    assert (await client.get(url)).json() is None
    created = await client.post(url)
    assert created.status_code == 200, created.text
    assert (await client.get(url)).json()["content"] == created.json()["content"]


async def test_study_sets_are_private(make_client: ClientFactory, fake_llm: FakeLLM) -> None:
    fake_llm.json_responders["multiple-choice"] = quiz_responder
    async with make_client() as a, make_client() as b:
        await register(a, "a")
        user_b = await register(b, "b")
        course_id = await create_course(a)
        await a.post(
            f"/api/courses/{course_id}/members", json={"email": user_b["email"], "role": "student"}
        )
        doc = await upload(a, course_id, "tcp.pdf", PDF)
        quiz = (
            await a.post(
                f"/api/courses/{course_id}/study-sets",
                json={"kind": "quiz", "count": 3, "document_id": doc["id"]},
            )
        ).json()
        assert (await b.get(f"/api/study-sets/{quiz['id']}")).status_code == 404
        assert (await b.get(f"/api/courses/{course_id}/study-sets")).json() == []


async def test_analytics_tracks_questions_and_unanswered(
    make_client: ClientFactory, fake_llm: FakeLLM
) -> None:
    async with make_client() as teacher, make_client() as student:
        await register(teacher, "teacher")
        s = await register(student, "student")
        course_id = await create_course(teacher)
        await teacher.post(
            f"/api/courses/{course_id}/members", json={"email": s["email"], "role": "student"}
        )
        await upload(teacher, course_id, "tcp.pdf", PDF)
        for q in ["How does slow start work?", "how does slow start work", "Receive window?"]:
            parse_sse(
                (await student.post("/api/chat", json={"course_id": course_id, "message": q})).text
            )

        empty_course = await create_course(teacher, "Empty")
        await teacher.post("/api/chat", json={"course_id": empty_course, "message": "Anything?"})

        assert (await student.get(f"/api/courses/{course_id}/analytics")).status_code == 403
        data = (await teacher.get(f"/api/courses/{course_id}/analytics")).json()
        assert data["totals"]["questions"] == 3
        assert data["totals"]["students"] == 1
        assert data["top_questions"][0]["count"] == 2
        assert data["top_documents"][0]["document_name"] == "tcp.pdf"

        empty = (await teacher.get(f"/api/courses/{empty_course}/analytics")).json()
        assert empty["totals"]["unanswered"] == 1
        assert empty["unanswered"][0]["question"] == "Anything?"
