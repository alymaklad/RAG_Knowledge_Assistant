"""LLM-assisted query processing: standalone rewriting of follow-ups, multi-query expansion."""

import json
import logging

from app.services.llm.client import LLMClient, Message

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """You rewrite follow-up questions into standalone search queries.
Given a conversation and a follow-up question, return one standalone question that contains \
every name and term needed to understand it without the conversation. Keep the language of \
the follow-up question. If it is already standalone, return it unchanged. Return only the \
question, with no preamble."""

EXPAND_PROMPT = """You help search lecture notes. Write {n} alternative phrasings of the \
student's question that use different wording or terminology a textbook might use. Keep each \
one short. Return JSON: {{"queries": ["...", "..."]}}"""


async def rewrite_standalone(llm: LLMClient, history: list[Message], question: str) -> str:
    """Turn "and how does it handle loss?" into "How does TCP handle packet loss?"."""
    if not history:
        return question
    transcript = "\n".join(f"{m['role'].title()}: {m['content'][:600]}" for m in history[-6:])
    messages: list[Message] = [
        {"role": "system", "content": REWRITE_PROMPT},
        {
            "role": "user",
            "content": f"Conversation:\n{transcript}\n\nFollow-up question: {question}",
        },
    ]
    try:
        result = await llm.complete(messages, temperature=0.0, max_tokens=120)
    except Exception:
        logger.exception("Query rewrite failed; using the original question")
        return question
    rewritten = result.text.strip().strip('"').strip()
    if not rewritten or len(rewritten) > 500:
        return question
    return rewritten


async def expand_queries(llm: LLMClient, question: str, n: int) -> list[str]:
    messages: list[Message] = [
        {"role": "system", "content": EXPAND_PROMPT.format(n=n)},
        {"role": "user", "content": question},
    ]
    try:
        result = await llm.complete(messages, temperature=0.3, max_tokens=300, json_mode=True)
        queries = json.loads(result.text).get("queries", [])
    except Exception:
        logger.exception("Query expansion failed; searching with the original question only")
        return []
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()][:n]
