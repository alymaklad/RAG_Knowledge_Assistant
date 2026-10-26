# AI Knowledge Assistant for University Courses — Implementation Plan

Source: `RAG_Knowledge_Assistant_Blueprint.docx` (v1.0). This plan turns the blueprint into buildable work, using the technologies highlighted in the doc as fixed choices, with one override: the frontend is **React** instead of the highlighted Next.js.

## 1. Locked technology stack

| Layer | Chosen (highlighted) | What changes vs. the blueprint's sample code |
|---|---|---|
| Backend API | **FastAPI** | Same as blueprint. Async throughout (SQLAlchemy async, `AsyncQdrantClient`). |
| Frontend | **React** (overrides the doc's Next.js highlight) | Single-page app: Vite + React + TypeScript, React Router, TanStack Query. Replaces the Streamlit MVP entirely; all Section 8 Streamlit code is reference only. No SSR needed: every page sits behind login, so SEO doesn't matter. |
| Vector DB | **Qdrant** | Same, but collections use **named dense + sparse vectors** from day 1 (see 3.2). |
| Embeddings | **BGE-m3 (BAAI)** | Replaces `text-embedding-3-small`. **1024 dims, not 1536.** Self-hosted, multilingual, 8192-token input. |
| RAG framework | **LangChain** | Utilities only (loaders, text splitters), custom retrieval/generation code, as the blueprint recommends. |
| Metadata DB | **PostgreSQL** | Same. SQLAlchemy 2.0 async + asyncpg + Alembic migrations. |

Not highlighted, so this plan uses the blueprint's own recommendation as the default (changeable later):

| Concern | Default | Notes |
|---|---|---|
| LLM | **`gpt-4o-mini`** (decided), via a configurable OpenAI-compatible client | Default model and the eval baseline. Local option: a Qwen model via Ollama (per the doc's "consider Qwen family" note; strong multilingual, which pairs with BGE-m3), switched by env vars only. |
| PDF extraction | PyMuPDF | `python-docx` for .docx, plain read for .txt. |
| Re-ranker | `BAAI/bge-reranker-v2-m3` | Swapped from the doc's `ms-marco-MiniLM` (English-only) to stay multilingual with BGE-m3. |
| Job queue | ARQ + Redis | Needed because BGE-m3 runs locally and is too heavy for FastAPI `BackgroundTasks`. Redis also backs rate limiting. |
| Evaluation | RAGAS + custom retrieval metrics | As Section 10. |
| Deployment | Docker Compose locally; Railway/Render + Qdrant Cloud | As Section 11. Note the embedding service needs ~3 GB RAM. |

## 2. Target architecture

```
 React SPA (web) ─HTTP/SSE─► FastAPI (api) ──► PostgreSQL
                                │   │
                                │   └──► Qdrant  (dense + sparse named vectors)
                                │            ▲
                                ├──► embedder (BGE-m3 service: dense + sparse)
                                │            ▲
                                ├──► Redis ──► worker (ARQ: extract → clean → chunk → embed → upsert)
                                │
                                └──► LLM (OpenAI-compatible: OpenAI / Ollama / vLLM)
```

Services in `docker-compose.yml`: `web`, `api`, `worker`, `embedder`, `postgres`, `qdrant`, `redis`. In development `web` is the Vite dev server; in production it's an Nginx container serving the built static files and proxying `/api` to FastAPI.

The SPA and the API are served from **the same origin** (Vite's dev proxy locally, Nginx in production). That keeps the httpOnly auth cookies first-party and avoids CORS configuration.

Why a separate `embedder` service: BGE-m3 is ~568M params (~2.2 GB weights). Both the worker (indexing) and the API (query embedding) need it; loading it once in one container avoids two copies in memory. It's a small FastAPI app wrapping `FlagEmbedding.BGEM3FlagModel` that returns `dense_vecs` and `lexical_weights` (sparse). Uses CUDA if available, CPU otherwise.

## 3. Key design decisions (and fixes to the blueprint)

### 3.1 Embeddings: BGE-m3
- Dense vector size **1024**, cosine distance. Every hardcoded `1536` in the blueprint must go; read the size from config.
- BGE-m3 also produces **sparse lexical weights**, which gives hybrid (keyword + semantic) search with no separate BM25 index. This moves hybrid search from a Phase 2 add-on to something built into the schema from the start.
- Chunk lengths are measured with the BGE-m3 (XLM-R) tokenizer via `RecursiveCharacterTextSplitter.from_huggingface_tokenizer(...)`. The blueprint's `length_function=len` counts characters, not tokens.
- Starting point: 800 tokens, 100 overlap (blueprint's recommendation), tuned in Phase 2 against the eval set.
- Similarity score thresholds (the blueprint's `0.7`) are model-specific. Calibrate for BGE-m3 on the golden dataset; start with no threshold and rely on top-k + re-ranking.

### 3.2 Qdrant layout
- **One collection (`course_chunks`) with `course_id` as a tenant payload index** (`is_tenant=True`), instead of one collection per course. This is Qdrant's recommended multitenancy pattern and avoids hundreds of small collections. `courses.vector_namespace` becomes optional; keep it if you want per-course collections later.
- Named vectors: `dense` (1024, cosine, HNSW) and `sparse` (sparse vector config, IDF modifier off since BGE-m3 weights are learned).
- Payload indexes on `course_id`, `document_id`.
- **Point ID = `chunks.id` in Postgres.** The blueprint generates a separate random UUID for the point, which breaks the link between the two stores.
- Use the Query API (`query_points` with `prefetch` + `FusionQuery(fusion=Fusion.RRF)`); `client.search` from the blueprint is deprecated.

### 3.3 PostgreSQL schema
Take Section 3.4 DDL as the base, plus:
- Add the missing `course_members (user_id, course_id, role, joined_at)` table with a composite PK; it's in the ER diagram but not the SQL.
- Add `quiz_generations` and `flashcard_sets` tables (JSONB payloads) for Phase 3.
- `documents.status` enum extended to: `uploaded, extracting, chunking, embedding, indexed, failed` (the UI's progress stages), plus `error_message TEXT`.
- `chunks`: add `section_header`, keep `metadata JSONB`. Unique `(document_id, chunk_index)`.
- `chat_messages.source_chunks` JSONB: `[{chunk_id, document_id, document_name, page_num, score}]`.
- Phase 3: `query_logs` table for analytics (question, course_id, user_id, retrieved chunk ids, top score, answered/unanswered flag, latency).
- All schema changes via Alembic, never raw DDL.

### 3.4 LLM provider abstraction
One `LLMClient` built on the `openai` SDK with `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` env vars. OpenAI, Ollama, vLLM, and most hosted providers expose OpenAI-compatible endpoints, so switching providers is a config change. Default is OpenAI `gpt-4o-mini`; the local profile points at Ollama (`http://ollama:11434/v1`) with a Qwen model, run as an optional `ollama` Compose service (`docker compose --profile local-llm up`). All eval baselines and reported scores use `gpt-4o-mini`; a Qwen run can be added as a comparison row, never as a replacement for the baseline. Low temperature (0.1) for Q&A, 0.7 for study content.

### 3.5 Streaming contract (API ↔ React)
`POST /api/chat` returns `text/event-stream` with typed events:
```
event: sources  data: [{chunk_id, document_name, page_num, score}, ...]   # sent first
event: token    data: {"t": "..."}
event: done     data: {"message_id": "...", "tokens_used": 123}
event: error    data: {"message": "..."}
```
The blueprint's endpoint never sends sources to the client; sending them first lets the UI render citations while the answer streams. Because it's a POST, the browser can't use `EventSource`; the frontend reads `fetch().body` with a stream parser. Save the user message **before** streaming and the assistant message on completion (also on client disconnect, with what was generated).

### 3.6 Security (built in from Phase 1, hardened in Phase 4)
- Auth: email/password, bcrypt hashing, JWT access token (short-lived) + refresh token, stored in **httpOnly cookies** set by FastAPI (not `localStorage`). In the SPA, a `<RequireAuth>` route wrapper calls `GET /api/auth/me` on load and redirects to `/login` on 401; the API stays the real enforcement point. Add CSRF protection for cookie auth (`SameSite=Lax` cookies + a double-submit CSRF token header on mutating requests).
- Every course-scoped endpoint goes through a `require_course_member(course_id)` dependency. Every Qdrant query includes a `course_id` filter derived from that check, never from raw client input. The blueprint's chat endpoint skips this check.
- Files: magic-byte MIME check, extension match, 50 MB cap, stored under random names outside any served path.
- Prompt injection: the blueprint's regex list is a weak first layer. The main defence: wrap retrieved context in clear delimiters, tell the model that context is untrusted data, and never put secrets in the prompt. Uploaded documents are an injection vector too, not just user questions.
- Rate limiting with `slowapi` backed by Redis (per user, not just per IP).

## 4. Repository structure

```
RAG_Knowledge_Assistant/
├─ docker-compose.yml
├─ .env.example
├─ .github/workflows/ci.yml
├─ backend/
│  ├─ pyproject.toml            # uv or poetry
│  ├─ Dockerfile
│  ├─ alembic/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ core/        config.py (pydantic-settings), security.py, deps.py, logging.py
│  │  ├─ db/          session.py, models/ (users, courses, documents, chunks, chat, study)
│  │  ├─ schemas/     Pydantic request/response models
│  │  ├─ api/routes/  auth, courses, documents, chat, study, analytics, health
│  │  ├─ services/
│  │  │  ├─ ingestion/   extract.py, clean.py, chunk.py, pipeline.py
│  │  │  ├─ embeddings/  client.py (calls embedder service)
│  │  │  ├─ vectorstore/ qdrant.py (collection setup, upsert, hybrid query, delete)
│  │  │  ├─ retrieval/   retriever.py, reranker.py, multi_query.py
│  │  │  ├─ llm/         client.py, prompts.py
│  │  │  └─ rag.py       orchestration: retrieve → rerank → build prompt → stream
│  │  └─ workers/     arq worker settings + ingest task
│  └─ tests/
├─ embedder/            small FastAPI app serving BGE-m3 (+ re-ranker)
│  ├─ Dockerfile
│  └─ main.py           POST /embed {texts, return_sparse} ; POST /rerank
├─ frontend/            React SPA (Vite, TypeScript, Tailwind, shadcn/ui)
│  ├─ Dockerfile        multi-stage: build with Node, serve with Nginx
│  ├─ nginx.conf        static files + SPA fallback + /api proxy (buffering off for SSE)
│  ├─ vite.config.ts    dev proxy /api → http://api:8000
│  └─ src/
│     ├─ main.tsx, router.tsx    React Router routes + <RequireAuth>
│     ├─ pages/         Login, Register, Dashboard, CourseDocuments, CourseChat, CourseStudy
│     ├─ components/    chat/, documents/, study/, ui/ (shadcn)
│     ├─ hooks/         useAuth, useChatStream, useDocumentStatus
│     └─ lib/
│        ├─ api/        generated types from FastAPI OpenAPI (openapi-typescript) + fetch wrapper
│        └─ sse.ts      POST-SSE stream parser
└─ eval/
   ├─ golden_dataset.jsonl
   ├─ generate_synthetic.py
   └─ run_eval.py       retrieval metrics + RAGAS, writes a report
```

## 5. Phased roadmap

The blueprint's 12-week plan assumed a Streamlit MVP. Building the UI in React from the start adds about a week, so this is 13 weeks at ~10–15 h/week. Each phase ends in something demoable.

### Phase 0 — Foundations (Week 1)
- Repo layout, `docker-compose.yml` with `postgres:16`, `qdrant/qdrant` (pinned version, not `latest`), `redis`.
- FastAPI skeleton: settings via `pydantic-settings`, `/health` and `/ready` (checks DB, Qdrant, Redis, embedder).
- SQLAlchemy models + first Alembic migration for the schema in 3.3.
- Embedder service: load BGE-m3, `/embed` returns dense + sparse. Verify output dim = 1024.
- Tooling: ruff, mypy, pytest, pre-commit; GitHub Actions running lint + tests.
- **Done when:** `docker compose up` brings all services healthy and `/ready` is green.

### Phase 1 — Core RAG MVP (Weeks 2–5)
**Week 2 — Ingestion pipeline**
- `POST /api/courses/{id}/documents` (multipart): validate, store file, create `documents` row, enqueue ARQ job.
- Worker: PyMuPDF extract per page → clean (Section 4.4 regexes) → token-aware recursive chunking → batch embed via embedder → upsert to Qdrant (dense + sparse, payload) → insert `chunks` rows → status `indexed`. Status updated at each stage; failures set `failed` + `error_message`.
- `DELETE` document removes Qdrant points (filter by `document_id`), chunks, file.
- Idempotent re-processing (delete existing points for the document first).
- **Done when:** upload a PDF and see correct points in the Qdrant dashboard with matching chunk rows.

**Week 3 — Retrieval + generation**
- Retriever: embed query → Qdrant query filtered by `course_id` (dense only to start, hybrid behind a flag).
- Context builder with `[Source N: doc, page]` labels; system prompt from Section 7.1.
- LLM client (3.4), streaming chat endpoint with the SSE contract (3.5), chat sessions/messages persisted.
- **Done when:** `curl` a question against an uploaded PDF and get a streamed, cited answer.

**Week 4 — Auth + course model**
- Register/login/refresh/logout, cookie-based JWT, `get_current_user`, `require_course_member`.
- Courses CRUD, membership (creator = instructor), list documents/sessions per course.
- Tests for isolation: user A can't read user B's course, documents, sessions, or search results.

**Week 5 — React frontend MVP**
- Vite + React + TypeScript scaffold, React Router, TanStack Query for server state, Tailwind + shadcn/ui.
- Login/register, dashboard (courses + stats), document page (drag-and-drop upload with progress, status badges polled via TanStack Query `refetchInterval` until `indexed`, delete).
- Chat page: session sidebar, streaming messages via a `useChatStream` hook over `lib/sse.ts`, Markdown rendering (`react-markdown` + KaTeX for formulas), collapsible citations with page + score, new chat.
- Typed API client generated from FastAPI's OpenAPI schema.
- **Done when:** the full flow works in the browser end to end.

### Phase 2 — Retrieval quality + evaluation (Weeks 6–8)
**Week 6 — Evaluation first**
- Golden dataset: 50 Q&A pairs from real course material (part handwritten, part synthetic via LLM, reviewed by hand). Include multilingual questions if the courses need it, since that's why BGE-m3 was picked.
- `eval/run_eval.py`: Hit Rate@K, MRR, Recall@K (Section 10.1) + RAGAS faithfulness, answer relevancy, context precision/recall. Record a **baseline** report.

**Week 7 — Retrieval improvements, each measured against the baseline**
- Hybrid dense + sparse with RRF fusion.
- Re-ranking: retrieve 20, re-rank with `bge-reranker-v2-m3`, keep 5.
- Calibrate score threshold; tune chunk size/overlap (e.g. 512/800/1024).
- Multi-query expansion behind a flag (it costs extra LLM calls, so keep it only if the metrics justify it).

**Week 8 — Conversation quality**
- Multi-turn: last N turns + history-aware query rewriting (rewrite follow-up questions into standalone queries before retrieval).
- "Not found in materials" behaviour tested explicitly.
- Prompt iteration driven by RAGAS scores; commit the before/after report.

### Phase 3 — Study tools + analytics (Weeks 9–11)
- **Week 9:** Quiz generator (Section 7.3 prompt, JSON validated with Pydantic, retry on invalid JSON) and flashcards (7.4), scoped to a document or a course; quiz and flashcard-flip UIs in React.
- **Week 10:** Document/chapter summaries (7.2), cached in Postgres; parent-child retrieval (retrieve small chunks, return the surrounding page/section) evaluated against the eval set; quiz export to PDF.
- **Week 11:** `query_logs` analytics; instructor dashboard with top questions, unanswered questions, most-cited documents/pages.

### Phase 4 — Hardening + deployment (Weeks 12–13)
- **Week 12:** Rate limiting, file-validation hardening, prompt-injection layer (3.6), structured logging + request IDs, error pages, load test (e.g. Locust) to back the latency/concurrency claims.
- **Week 13:** Deploy (Railway/Render for api/worker/embedder plus the Nginx `web` container serving the React build, managed Postgres, Qdrant Cloud, file storage on S3-compatible/R2), HTTPS, secrets in platform env vars, CI/CD on push to `main`, README per Section 14.4, demo video.

## 6. Testing strategy
- **Unit:** cleaning, chunking (token counts within bounds, overlap present), prompt building, SSE formatting, JSON parsing of quiz output.
- **Integration (pytest + Docker services):** upload → indexed → query returns chunks from that document; delete removes everything; cross-course isolation.
- **Fakes:** a deterministic fake embedder and fake LLM so CI doesn't download BGE-m3 or call paid APIs.
- **Eval:** `run_eval.py` run manually per retrieval/prompt change; results committed to `eval/reports/`.
- **Frontend:** Vitest + React Testing Library for components and the SSE parser; Playwright smoke test for login → upload → ask.

## 7. Configuration (`.env.example`)
```
DATABASE_URL=postgresql+asyncpg://...
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
REDIS_URL=redis://redis:6379/0
EMBEDDER_URL=http://embedder:8001
EMBEDDING_DIM=1024
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=
# Local alternative (Ollama + Qwen, compose profile "local-llm"):
# LLM_BASE_URL=http://ollama:11434/v1
# LLM_MODEL=<qwen model tag pulled into Ollama>
# LLM_API_KEY=ollama
JWT_SECRET_KEY=
CHUNK_SIZE_TOKENS=800
CHUNK_OVERLAP_TOKENS=100
RETRIEVAL_TOP_K=20
RERANK_TOP_N=5
HYBRID_SEARCH=true
MAX_UPLOAD_MB=50
```

## 8. Risks and mitigations
| Risk | Mitigation |
|---|---|
| BGE-m3 slow on CPU for large uploads | GPU if available; batch embedding; async worker so the UI never blocks; show per-stage progress. |
| Hosting cost/RAM for the embedder in production | Run the embedder on a single small instance shared by api + worker; or use a hosted BGE-m3 endpoint behind the same `/embed` interface. |
| Scanned PDFs / image-only slides yield no text | Detect near-empty pages and flag them on the document; OCR (Tesseract via Unstructured) as a later add-on. |
| Hallucinated or uncited answers | Grounding prompt, re-ranking, faithfulness tracked in eval; UI always shows sources. |
| Data leakage between courses | Membership dependency on every route + mandatory `course_id` filter in the vector store wrapper + isolation tests. |
| Blueprint CV metrics (e.g. "0.87 faithfulness") are examples | Only quote numbers produced by `run_eval.py` on your own dataset. |

## 9. Open decisions
Decided: default LLM and eval baseline is `gpt-4o-mini`; Qwen via Ollama is the local option (see 3.4).

1. **Course languages**: if courses are non-English, the golden dataset and prompts should include that language from Week 6.
2. **Hosting target** for the embedder (CPU instance vs. GPU vs. hosted endpoint), decided by Week 12.

## 10. Implementation notes (what changed while building)

| Plan said | Built | Why |
|---|---|---|
| shadcn/ui components | Small hand-written components (`frontend/src/components/ui.tsx`) | The UI needs ~6 primitives; avoids a generator step and keeps the bundle small |
| `python-magic` for MIME checks | `filetype` (pure Python) + UTF-8 text sniffing | `python-magic` needs libmagic DLLs on Windows |
| FlagEmbedding for BGE-m3 | Direct `transformers` inference (normalized CLS dense + `sparse_linear.pt` lexical weights) | Fewer dependencies, no version pinning against transformers |
| `quiz_generations` + `flashcard_sets` tables | One `study_sets` table with a `kind` column, plus `document_summaries` and `query_logs` | Same shape for both kinds of study set |
| Collection per course (blueprint) | One collection, `course_id` tenant index | Qdrant's recommended multitenancy pattern |
| Default ports 5432/6333/6379/8000 | Host ports 5433/6335/6380/8010 | Avoid clashing with other local stacks; container ports unchanged |
| Ollama default context | `OLLAMA_CONTEXT_LENGTH=16384` documented | Ollama's 4k default truncates RAG prompts |
| Deploy to Railway/Render | `render.yaml` blueprint + `docker-compose.prod.yml`; not deployed | Deploying needs the owner's accounts and secrets |

The UI is named **Margin**: answers cite sources as sidenotes in the margin, with the supporting
sentence highlighted. Off-white, light-only theme; Literata for reading, Atkinson Hyperlegible
Next for interface text.
