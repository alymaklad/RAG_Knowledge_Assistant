"""Evaluate retrieval (and optionally generation) on the golden dataset.

Indexes the sample corpus (eval/corpus/pdf) into a separate Qdrant collection with the real
pipeline code, then runs each named configuration over every question.

Retrieval metrics (no LLM needed): Hit@K, MRR@K, Recall@K, Precision@K. A retrieved chunk is
relevant when it contains one of the question's `evidence` strings, so the labels survive
changes to chunk size.

Generation metrics (--generate): citation rate, cited-source relevance, key-term coverage,
abstention on unanswerable questions, false abstention on answerable ones, latency. With
--ragas and the `eval` dependency group installed, RAGAS faithfulness / answer relevancy are
added, judged by the configured LLM.

    uv run --project backend python eval/run_eval.py --configs baseline,hybrid,rerank,hybrid_rerank
    uv run --project backend python eval/run_eval.py --configs hybrid_rerank --generate
"""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

from app.core.config import Settings, get_settings  # noqa: E402
from app.services.container import Services, build_services  # noqa: E402
from app.services.ingestion.chunk import chunk_pages  # noqa: E402
from app.services.ingestion.extract import extract  # noqa: E402
from app.services.llm.prompts import NOT_FOUND_ANSWER  # noqa: E402
from app.services.rag import stream_answer  # noqa: E402
from app.services.retrieval.retriever import RetrievedChunk, retrieve  # noqa: E402
from app.services.vectorstore.qdrant import ChunkPoint, VectorStore  # noqa: E402

EVAL_COURSE = uuid.UUID("00000000-0000-0000-0000-00000000e7a1")
K = 5

# Named retrieval configurations (overrides on top of the environment's settings).
CONFIGS: dict[str, dict[str, Any]] = {
    "baseline": {"hybrid_search": False, "rerank_enabled": False, "multi_query": False},
    "hybrid": {"hybrid_search": True, "rerank_enabled": False, "multi_query": False},
    "rerank": {"hybrid_search": False, "rerank_enabled": True, "multi_query": False},
    "hybrid_rerank": {"hybrid_search": True, "rerank_enabled": True, "multi_query": False},
    "hybrid_rerank_mq": {"hybrid_search": True, "rerank_enabled": True, "multi_query": True},
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class Item:
    id: str
    question: str
    answer: str
    evidence: list[str]
    key_terms: list[str]
    type: str
    doc: str | None

    def is_relevant(self, chunk_text: str) -> bool:
        t = norm(chunk_text)
        return any(norm(e) in t for e in self.evidence)


def load_dataset(path: Path) -> list[Item]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            items.append(
                Item(
                    id=d["id"],
                    question=d["question"],
                    answer=d["answer"],
                    evidence=d.get("evidence", []),
                    key_terms=d.get("key_terms", []),
                    type=d.get("type", "factual"),
                    doc=d.get("doc"),
                )
            )
    return items


@dataclass
class Index:
    collection: str
    chunk_texts: list[str] = field(default_factory=list)


async def build_index(services: Services, settings: Settings, corpus: Path) -> Index:
    collection = f"eval_c{settings.chunk_size_tokens}_o{settings.chunk_overlap_tokens}"
    store = VectorStore(services.vectors.client, collection, settings.embedding_dim)
    if await store.client.collection_exists(collection):
        await store.client.delete_collection(collection)
    await store.ensure_collection()
    index = Index(collection)
    pdfs = sorted(corpus.glob("*.pdf"))  # noqa: ASYNC240 - one-off script
    if not pdfs:
        sys.exit(f"No PDFs in {corpus}; run eval/build_corpus.py first.")
    for pdf in pdfs:
        extracted = extract(str(pdf), "application/pdf")
        chunks = chunk_pages(
            extracted.pages,
            chunk_size=settings.chunk_size_tokens,
            chunk_overlap=settings.chunk_overlap_tokens,
            tokenizer_name=settings.chunk_tokenizer,
        )
        emb = await services.embedder.embed([c.embedding_text for c in chunks])
        doc_id = str(uuid.uuid5(EVAL_COURSE, pdf.name))
        await store.upsert(
            [
                ChunkPoint(
                    id=uuid.uuid4(),
                    dense=emb.dense[i],
                    sparse=emb.sparse[i] if emb.sparse else None,
                    payload={
                        "course_id": str(EVAL_COURSE),
                        "document_id": doc_id,
                        "document_name": pdf.name,
                        "chunk_index": c.chunk_index,
                        "page_num": c.page_num,
                        "section_header": c.section_header,
                        "text": c.text,
                    },
                )
                for i, c in enumerate(chunks)
            ]
        )
        index.chunk_texts.extend(c.text for c in chunks)
    services.vectors = store
    return index


def retrieval_metrics(item: Item, chunks: list[RetrievedChunk], index: Index) -> dict[str, float]:
    rels = [item.is_relevant(c.text) for c in chunks[:K]]
    total_relevant = sum(item.is_relevant(t) for t in index.chunk_texts)
    first = next((i for i, r in enumerate(rels) if r), None)
    return {
        "hit1": float(bool(rels) and rels[0]),
        "hit": float(first is not None),
        "mrr": 1.0 / (first + 1) if first is not None else 0.0,
        "recall": sum(rels) / total_relevant if total_relevant else 0.0,
        "precision": sum(rels) / len(rels) if rels else 0.0,
        "top_score": chunks[0].display_score if chunks else 0.0,
    }


CITE_RE = re.compile(r"\[Sources?\s*([\d,\s]+(?:and\s*\d+)?)\]", re.I)


def is_abstention(answer: str) -> bool:
    a = answer.lower()
    return (
        "could not find" in a or "couldn't find" in a or a.startswith(NOT_FOUND_ANSWER[:40].lower())
    )


async def generate(
    services: Services, item: Item, index: Index
) -> tuple[dict[str, float], dict[str, Any]]:
    start = time.perf_counter()
    first_token: float | None = None
    parts: list[str] = []
    sources: list[RetrievedChunk] = []
    async for ev in stream_answer(
        services, course_id=EVAL_COURSE, question=item.question, history=[]
    ):
        if ev.kind == "sources" and ev.sources is not None:
            sources = ev.sources
        elif ev.kind == "token" and ev.token:
            if first_token is None:
                first_token = time.perf_counter() - start
            parts.append(ev.token)
    answer = "".join(parts)
    cited = {int(n) for m in CITE_RE.findall(answer) for n in re.findall(r"\d+", m)}
    valid = {n for n in cited if 1 <= n <= len(sources)}
    out: dict[str, float] = {
        "latency_s": time.perf_counter() - start,
        "first_token_s": first_token or 0.0,
        "abstained": float(is_abstention(answer)),
    }
    if item.type != "unanswerable":
        out["cited"] = float(bool(valid))
        out["invalid_citation"] = float(bool(cited - valid))
        out["cited_relevant"] = float(any(item.is_relevant(sources[n - 1].text) for n in valid))
        if item.key_terms:
            out["key_terms"] = sum(t.lower() in answer.lower() for t in item.key_terms) / len(
                item.key_terms
            )
    record = {
        "id": item.id,
        "question": item.question,
        "answer": answer,
        "contexts": [c.text for c in sources],
        "ground_truth": item.answer,
    }
    return out, record


def mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 3) if values else float("nan")


def _ragas_imports() -> Any:
    """Import RAGAS. RAGAS 0.4 still imports a langchain-community module that was removed in
    langchain-community 0.4; it only uses it for an isinstance check, so a stub is enough."""
    import types
    import warnings

    name = "langchain_community.chat_models.vertexai"
    if name not in sys.modules:
        stub = types.ModuleType(name)
        stub.ChatVertexAI = type("ChatVertexAI", (), {})  # type: ignore[attr-defined]
        sys.modules[name] = stub
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")
    import ragas
    import ragas.metrics

    return ragas


async def run_ragas(records: list[dict[str, Any]], settings: Settings) -> dict[str, float]:
    try:
        import httpx
        from langchain_core.embeddings import Embeddings
        from langchain_openai import ChatOpenAI

        ragas = _ragas_imports()
    except ImportError:
        print("RAGAS not installed (uv sync --group eval); skipping.", file=sys.stderr)
        return {}

    class BgeEmbeddings(Embeddings):
        """Use our own BGE-m3 service for RAGAS' answer-relevancy embeddings."""

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            r = httpx.post(
                f"{settings.embedder_url}/embed",
                json={"texts": texts, "sparse": False},
                timeout=600,
            )
            r.raise_for_status()
            return list(r.json()["dense"])

        def embed_query(self, text: str) -> list[float]:
            return self.embed_documents([text])[0]

    llm = ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "unused",
        temperature=0,
        timeout=300,
    )
    dataset = ragas.EvaluationDataset.from_list(
        [
            {
                "user_input": r["question"],
                "response": r["answer"],
                "retrieved_contexts": r["contexts"],
                "reference": r["ground_truth"],
            }
            for r in records
        ]
    )
    metrics = [
        ragas.metrics.Faithfulness(),
        ragas.metrics.AnswerRelevancy(),
        ragas.metrics.LLMContextRecall(),
    ]
    result = await asyncio.to_thread(
        ragas.evaluate,
        dataset,
        metrics=metrics,
        llm=llm,
        embeddings=BgeEmbeddings(),
        show_progress=False,
    )
    df = result.to_pandas()
    return {c: round(float(df[c].mean()), 3) for c in df.columns if df[c].dtype.kind == "f"}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--configs", default="baseline,hybrid,rerank,hybrid_rerank")
    parser.add_argument("--dataset", default=str(ROOT / "golden_dataset.jsonl"))
    parser.add_argument("--corpus", default=str(ROOT / "corpus" / "pdf"))
    parser.add_argument("--chunk-size", type=int)
    parser.add_argument("--chunk-overlap", type=int)
    parser.add_argument("--generate", action="store_true", help="also generate answers")
    parser.add_argument("--ragas", action="store_true", help="add RAGAS metrics (needs --generate)")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    base = get_settings()
    updates: dict[str, Any] = {}
    if args.chunk_size:
        updates["chunk_size_tokens"] = args.chunk_size
    if args.chunk_overlap is not None:
        updates["chunk_overlap_tokens"] = args.chunk_overlap
    base = base.model_copy(update=updates)

    items = load_dataset(Path(args.dataset))
    services = build_services(base)
    index = await build_index(services, base, Path(args.corpus))
    print(f"Indexed {len(index.chunk_texts)} chunks into {index.collection}")
    unmatched = [
        i.id for i in items if i.evidence and not any(i.is_relevant(t) for t in index.chunk_texts)
    ]
    if unmatched:
        print(f"WARNING: evidence not found in any chunk for: {unmatched}", file=sys.stderr)

    answerable = [i for i in items if i.type != "unanswerable"]
    results: dict[str, dict[str, Any]] = {}
    for name in args.configs.split(","):
        settings = base.model_copy(update=CONFIGS[name])
        services.settings = settings
        rows: dict[str, list[float]] = {}
        top_scores: dict[str, list[float]] = {"answerable": [], "unanswerable": []}
        per_question: list[dict[str, Any]] = []
        started = time.perf_counter()
        for item in items:
            chunks = await retrieve(
                services, course_id=EVAL_COURSE, query=item.question, settings=settings
            )
            m = retrieval_metrics(item, chunks, index)
            per_question.append(
                {"id": item.id, "type": item.type, "hit": m["hit"], "top_score": m["top_score"]}
            )
            top_scores["unanswerable" if item.type == "unanswerable" else "answerable"].append(
                m.pop("top_score")
            )
            if item.type != "unanswerable":
                for k, v in m.items():
                    rows.setdefault(k, []).append(v)
        summary: dict[str, Any] = {k: mean(v) for k, v in rows.items()}
        summary["retrieval_s_per_query"] = round((time.perf_counter() - started) / len(items), 3)
        summary["mean_top_score_answerable"] = mean(top_scores["answerable"])
        summary["mean_top_score_unanswerable"] = mean(top_scores["unanswerable"])
        by_type: dict[str, float] = {}
        for t in sorted({i.type for i in answerable}):
            subset = [i for i in answerable if i.type == t]
            hits = []
            for item in subset:
                chunks = await retrieve(
                    services, course_id=EVAL_COURSE, query=item.question, settings=settings
                )
                hits.append(retrieval_metrics(item, chunks, index)["hit"])
            by_type[t] = mean(hits)
        summary["hit_by_type"] = by_type
        summary["per_question"] = per_question
        answerable_scores = [q["top_score"] for q in per_question if q["type"] != "unanswerable"]
        unanswerable_scores = [q["top_score"] for q in per_question if q["type"] == "unanswerable"]
        summary["min_top_score_answerable"] = round(min(answerable_scores), 4)
        summary["max_top_score_unanswerable"] = round(max(unanswerable_scores or [0.0]), 4)

        if args.generate:
            gen_rows: dict[str, list[float]] = {}
            unans: list[float] = []
            records = []
            for item in items:
                out, record = await generate(services, item, index)
                records.append(record)
                if item.type == "unanswerable":
                    unans.append(out["abstained"])
                    continue
                gen_rows.setdefault("false_abstention", []).append(out.pop("abstained"))
                for k, v in out.items():
                    gen_rows.setdefault(k, []).append(v)
            summary["generation"] = {k: mean(v) for k, v in gen_rows.items()}
            summary["generation"]["abstention_on_unanswerable"] = mean(unans)
            summary["generation"]["llm_model"] = settings.llm_model
            if args.ragas:
                summary["ragas"] = await run_ragas(
                    [r for r, i in zip(records, items, strict=True) if i.type != "unanswerable"],
                    settings,
                )
            summary["_records"] = records
        results[name] = summary
        print(
            f"{name}: "
            + ", ".join(f"{k}={v}" for k, v in summary.items() if not isinstance(v, (dict, list)))
        )

    write_report(results, base, len(items), len(index.chunk_texts), args.label)
    await services.aclose()


def write_report(
    results: dict[str, dict[str, Any]], settings: Settings, n_items: int, n_chunks: int, label: str
) -> None:
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    slug = f"{stamp}{'-' + label if label else ''}"
    (out_dir / f"{slug}.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    embeddings = (
        f"BGE-m3 via {settings.embedder_url}"
        if settings.embedder_backend == "http"
        else "hash (test only)"
    )
    lines = [
        f"# Evaluation report {slug}",
        "",
        f"- Questions: {n_items} (golden_dataset.jsonl); chunks indexed: {n_chunks}",
        f"- Chunking: {settings.chunk_size_tokens} tokens, overlap {settings.chunk_overlap_tokens} "
        f"({settings.chunk_tokenizer})",
        f"- Embeddings: {embeddings}",
        f"- Retrieval candidates: {settings.retrieval_top_k}, kept: {settings.rerank_top_n}; "
        f"metrics @ {K}",
        "",
        "## Retrieval (answerable questions)",
        "",
        "| Config | Hit@1 | Hit@5 | MRR@5 | Recall@5 | Precision@5 | Hit@5 (multilingual) "
        "| s/query |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, s in results.items():
        lines.append(
            f"| {name} | {s['hit1']} | {s['hit']} | {s['mrr']} | {s['recall']} | "
            f"{s['precision']} | "
            f"{s['hit_by_type'].get('multilingual', '-')} | {s['retrieval_s_per_query']} |"
        )
    lines += [
        "",
        "Top-1 score, answerable vs unanswerable (used to calibrate a relevance threshold):",
        "",
    ]
    for name, s in results.items():
        lines.append(
            f"- {name}: mean {s['mean_top_score_answerable']} vs "
            f"{s['mean_top_score_unanswerable']}; lowest answerable "
            f"{s['min_top_score_answerable']}, highest unanswerable "
            f"{s['max_top_score_unanswerable']}"
        )
    gen = {n: s["generation"] for n, s in results.items() if "generation" in s}
    if gen:
        lines += [
            "",
            "## Generation",
            "",
            "| Config | Model | Cited | Cited source relevant | Key terms | Invalid citation | "
            "False abstention | Abstains when unanswerable | First token (s) | Total (s) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for name, g in gen.items():
            lines.append(
                f"| {name} | {g['llm_model']} | {g.get('cited')} | {g.get('cited_relevant')} | "
                f"{g.get('key_terms')} | {g.get('invalid_citation')} | "
                f"{g.get('false_abstention')} | {g['abstention_on_unanswerable']} | "
                f"{g.get('first_token_s')} | {g.get('latency_s')} |"
            )
    ragas = {n: s["ragas"] for n, s in results.items() if s.get("ragas")}
    if ragas:
        lines += ["", "## RAGAS", ""]
        for name, r in ragas.items():
            lines.append(f"- {name}: " + ", ".join(f"{k} {v}" for k, v in r.items()))
    (out_dir / f"{slug}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {out_dir / (slug + '.md')}")


if __name__ == "__main__":
    asyncio.run(main())
