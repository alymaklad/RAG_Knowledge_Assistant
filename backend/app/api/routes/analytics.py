"""Instructor analytics over query_logs: what students ask, what the materials can't answer,
and which documents and sections answers lean on."""

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import Date, cast, func, select

from app.core.deps import DbSession, InstructorMembership
from app.db.models import QueryLog

router = APIRouter(tags=["analytics"])


def _normalize(question: str) -> str:
    return " ".join(question.lower().strip(" ?!.").split())


@router.get("/courses/{course_id}/analytics")
async def course_analytics(
    course_id: uuid.UUID,
    member: InstructorMembership,
    db: DbSession,
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    base = (QueryLog.course_id == course_id, QueryLog.created_at >= since)

    totals = (
        await db.execute(
            select(
                func.count(QueryLog.id),
                func.count(func.distinct(QueryLog.user_id)),
                func.count(QueryLog.id).filter(QueryLog.answered.is_(False)),
                func.avg(QueryLog.latency_ms),
            ).where(*base)
        )
    ).one()

    day = cast(QueryLog.created_at, Date)
    per_day = (
        await db.execute(select(day, func.count()).where(*base).group_by(day).order_by(day))
    ).all()

    # Grouping on normalized text in Python keeps this portable; volumes per course are small.
    rows = (
        await db.execute(
            select(
                QueryLog.question,
                QueryLog.answered,
                QueryLog.created_at,
                QueryLog.retrieved,
                QueryLog.cited,
            )
            .where(*base)
            .order_by(QueryLog.created_at.desc())
            .limit(5000)
        )
    ).all()

    asked: Counter[str] = Counter()
    display: dict[str, str] = {}
    unanswered: Counter[str] = Counter()
    last_unanswered: dict[str, datetime] = {}
    doc_citations: Counter[str] = Counter()
    section_citations: Counter[tuple[str, str | None, int | None]] = Counter()
    for question, answered, created_at, retrieved, cited in rows:
        key = _normalize(question)
        asked[key] += 1
        display.setdefault(key, question.strip())
        if not answered:
            unanswered[key] += 1
            last_unanswered.setdefault(key, created_at)
        for n in cited or []:
            if 1 <= n <= len(retrieved or []):
                src = retrieved[n - 1]
                doc_citations[src.get("document_name") or "Unknown"] += 1
                section_citations[
                    (
                        src.get("document_name") or "Unknown",
                        src.get("section_header"),
                        src.get("page_num"),
                    )
                ] += 1

    return {
        "days": days,
        "totals": {
            "questions": totals[0],
            "students": totals[1],
            "unanswered": totals[2],
            "avg_latency_ms": round(totals[3]) if totals[3] is not None else None,
        },
        "per_day": [{"day": d.isoformat(), "questions": n} for d, n in per_day],
        "top_questions": [{"question": display[k], "count": c} for k, c in asked.most_common(10)],
        "unanswered": [
            {"question": display[k], "count": c, "last_asked": last_unanswered[k].isoformat()}
            for k, c in unanswered.most_common(15)
        ],
        "top_documents": [
            {"document_name": d, "citations": c} for d, c in doc_citations.most_common(8)
        ],
        "top_sections": [
            {"document_name": d, "section": s, "page_num": p, "citations": c}
            for (d, s, p), c in section_citations.most_common(8)
        ],
    }
