# Evaluation results

Golden set: 52 questions over the three sample handouts in `eval/corpus/` (46 factual,
3 cross-lingual in Arabic/Spanish/French, 3 unanswerable). Relevance = the retrieved chunk
contains the question's evidence text. Embeddings: real BGE-m3 (dense + sparse) on an RTX 4070;
reranker bge-reranker-v2-m3. Raw reports are in `eval/reports/`.

## Retrieval (answerable questions, top 5)

| Config | Hit@1 | Hit@5 | MRR@5 | s/query |
|---|---|---|---|---|
| Dense only (baseline) | 0.898 | 0.980 | 0.932 | 0.07 |
| Hybrid dense + sparse (RRF) | 0.918 | 0.980 | 0.949 | 0.07 |
| Dense + re-rank | 0.959 | 1.000 | 0.980 | 0.42 |
| **Hybrid + re-rank (default)** | **0.959** | **1.000** | **0.980** | **0.41** |
| Hybrid + re-rank + multi-query | 0.959 | 1.000 | 0.980 | 2.49 |

- Cross-lingual questions hit the right passage in every configuration (BGE-m3).
- Re-ranking is the single biggest gain: first-result accuracy 0.90 to 0.96, MRR 0.93 to 0.98.
- Multi-query expansion (3 LLM paraphrases) added 2 s per question and no accuracy here, so it
  ships off (`MULTI_QUERY=false`).
- Chunk size 256 / 512 / 800 tokens gave identical results: chunks never cross section
  boundaries and the handout sections are short, so sections, not the size limit, set the
  chunks. Revisit on long textbook chapters.
- On CPU the reranker takes about 9.8 s per question (20 candidates); on the GPU 0.4 s. Without a
  GPU, lower `RETRIEVAL_TOP_K` or turn re-ranking off.

### Neighbour expansion (parent-child retrieval)

`CONTEXT_NEIGHBORS=1` replaces each retrieved chunk with itself plus the chunks on either side.
On hybrid + re-rank it raised Hit@1 from 0.959 to 1.000 (MRR 0.980 to 1.000), partly by
construction: a longer passage is more likely to contain the evidence. Each passage sent to the
LLM grows two to three times, which matters for small local models (Ollama's default 4k
context), so it ships off and is worth enabling with long-context models.

## "Not in your materials" threshold

| Score used | Lowest answerable top-1 | Highest unanswerable top-1 |
|---|---|---|
| Dense cosine | 0.448 | 0.519 (overlaps: unusable) |
| Reranker (0 to 1) | 0.386 | 0.011 |

The reranker separates answerable from unanswerable questions with a wide gap, so
`RERANK_THRESHOLD=0.1` is the default. Passages below it are dropped; if none remain, the API
answers "not found" without calling the LLM. With the threshold on, Precision@5 rises from 0.20
to 0.83 (fewer irrelevant passages reach the prompt) with no loss in Hit@5.

## Generation

Run with `qwen2.5:7b-instruct` through Ollama as a stand-in, because no OpenAI key was
available while building. The configured default (and the baseline to report) is `gpt-4o-mini`:
re-run with `LLM_API_KEY` set to get those numbers.

| Config | Cited | Cited source relevant | Key terms | Invalid citations | False abstention | Abstains when unanswerable |
|---|---|---|---|---|---|---|
| Hybrid, no re-rank | 1.00 | 0.96 | 0.94 | 0.00 | 0.00 | 1.00 |
| **Hybrid + re-rank + threshold** | **1.00** | **1.00** | **0.94** | **0.00** | **0.00** | **1.00** |

- Prompt v1 already cited every answer and declined every unanswerable question, so the prompt
  was not changed; the improvement came from retrieval (every cited source is now relevant).
- Time to first token was 1.4 to 1.6 s. Full answers took 5.6 s without re-ranking and 14 s with
  it in this run, because Qwen and the GPU embedder shared one 8 GB laptop GPU. With a hosted LLM
  the re-ranking cost is the 0.4 s above.
- RAGAS (faithfulness, answer relevancy, context recall) is wired in (`--ragas`, `uv sync --group
  eval`) and judged by the configured LLM; it was not run for this table because a 7B local
  judge is not a reliable grader.

## Reproduce

```bash
uv run --project backend python eval/build_corpus.py
uv run --project backend python eval/run_eval.py --configs baseline,hybrid,rerank,hybrid_rerank,hybrid_rerank_mq
uv run --project backend python eval/run_eval.py --configs hybrid_rerank --generate
```
