"""Load test for the chat path (Locust).

    pip install locust
    locust -f eval/locustfile.py --host http://localhost:8010 --users 20 --spawn-rate 2 \
        --headless --run-time 3m --csv eval/reports/load

Each simulated student signs in (demo account from backend/scripts/seed_demo.py), picks the
demo course and asks questions, reading the SSE stream to the end. `time to first token` and
`full answer` are reported as separate entries. Rate limits must be raised (RATE_LIMIT_CHAT)
or disabled (RATE_LIMIT_ENABLED=false) on the target, since all users share one account.
"""

import json
import random
import time

from locust import HttpUser, between, events, task

QUESTIONS = [
    "What is a Markov blanket?",
    "How does slow start grow the congestion window?",
    "What does the Viterbi algorithm compute?",
    "Why does TCP use random initial sequence numbers?",
    "What is explaining away?",
    "How does Baum-Welch learn HMM parameters?",
]


class Student(HttpUser):
    wait_time = between(2, 6)

    def on_start(self) -> None:
        resp = self.client.post(
            "/api/auth/login",
            json={"email": "demo@example.edu", "password": "demo-password-123"},
            name="login",
        )
        token = resp.json()["access_token"]
        self.client.headers["Authorization"] = f"Bearer {token}"
        courses = self.client.get("/api/courses", name="courses").json()
        self.course_id = courses[0]["id"]

    @task
    def ask(self) -> None:
        start = time.perf_counter()
        first_token = None
        with self.client.post(
            "/api/chat",
            json={"course_id": self.course_id, "message": random.choice(QUESTIONS)},
            stream=True,
            catch_response=True,
            name="chat (stream opened)",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            event = ""
            for raw in resp.iter_lines():
                line = raw.decode() if isinstance(raw, bytes) else raw
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "token" and first_token is None:
                    first_token = time.perf_counter() - start
                elif line.startswith("data: ") and event == "error":
                    resp.failure(json.loads(line[6:]).get("message", "error"))
                    return
            resp.success()
        total = time.perf_counter() - start
        for name, value in (("time to first token", first_token), ("full answer", total)):
            if value is not None:
                events.request.fire(
                    request_type="SSE",
                    name=name,
                    response_time=value * 1000,
                    response_length=0,
                    exception=None,
                    context={},
                )
