"""Create a demo account and course, and upload the sample corpus through the public API.

Usage (API running, sample PDFs built with eval/build_corpus.py):
    uv run python scripts/seed_demo.py [--api http://localhost:8010]

Demo login (local development only):  demo@example.edu / demo-password-123
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

DEMO_EMAIL = "demo@example.edu"
DEMO_PASSWORD = "demo-password-123"
COURSE_NAME = "CS 221: Probabilistic Models & Networks (demo)"
CORPUS = Path(__file__).resolve().parents[2] / "eval" / "corpus" / "pdf"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8010")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=120) as http:
        resp = http.post("/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        if resp.status_code == 401:
            resp = http.post(
                "/api/auth/register",
                json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD, "full_name": "Demo Student"},
            )
        resp.raise_for_status()
        http.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

        courses = http.get("/api/courses").json()
        course = next((c for c in courses if c["name"] == COURSE_NAME), None)
        if course is None:
            course = http.post(
                "/api/courses",
                json={
                    "name": COURSE_NAME,
                    "description": "Sample lecture handouts used for demos and evaluation.",
                },
            ).json()
        course_id = course["id"]

        existing = {d["filename"] for d in http.get(f"/api/courses/{course_id}/documents").json()}
        pdfs = sorted(CORPUS.glob("*.pdf"))
        if not pdfs:
            sys.exit(f"No PDFs in {CORPUS}. Run eval/build_corpus.py first.")
        for pdf in pdfs:
            if pdf.name in existing:
                continue
            with pdf.open("rb") as fh:
                r = http.post(
                    f"/api/courses/{course_id}/documents",
                    files={"file": (pdf.name, fh, "application/pdf")},
                )
            r.raise_for_status()
            print(f"uploaded {pdf.name}")

        for _ in range(120):
            docs = http.get(f"/api/courses/{course_id}/documents").json()
            pending = [d for d in docs if d["status"] not in ("indexed", "failed")]
            if not pending:
                break
            time.sleep(2)
        for d in docs:
            print(f"{d['filename']}: {d['status']} ({d['chunk_count']} chunks)")
        print(f"course_id={course_id}")


if __name__ == "__main__":
    main()
