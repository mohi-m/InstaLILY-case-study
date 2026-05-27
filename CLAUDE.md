# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Prerequisites
- Python 3.11+
- Node.js 22+
- PostgreSQL 16 with the [pgvector](https://github.com/pgvector/pgvector) extension enabled

Create the database and enable pgvector once:
```sql
CREATE DATABASE partselect;
\c partselect
CREATE EXTENSION IF NOT EXISTS vector;
```

### Set up environment
```bash
cp .env.example .env   # fill in OPENAI_API_KEY (and DATABASE_URL if your PG credentials differ)
```

### Start the backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Verify: `curl localhost:8000/health` → `{"status":"ok"}`

### Start the frontend
```bash
cd frontend
npm install
npm run dev
```

### Populate the database (run once)
```bash
cd scraper
pip install -r requirements.txt
playwright install chromium
python run.py
```
Re-running is safe (idempotent upserts). PartSelect blocks plain HTTP; the scraper needs a real browser and may need a non-blocked network.

### Backend tests
```bash
cd backend
pip install -r requirements.txt
pytest                             # all tests
pytest tests/test_hybrid_rrf.py   # single file
```
`conftest.py` adds both `backend/` and `scraper/` to `sys.path`, so scraper modules are importable from tests. `asyncio_mode = auto` is set in `pytest.ini`.

### Hit the API directly
```bash
curl -N localhost:8000/api/chat -H 'Content-Type: application/json' -d \
  '{"messages":[{"role":"user","content":"How do I install PS11752778?"}]}'
```

## Architecture

```
Next.js (scaffold) ──SSE──▶ FastAPI ──▶ LangGraph agent (GPT-5.4-mini)
                                               │
                              Hybrid search (Postgres FTS + pgvector RRF)
                                               │
                    Postgres 16 + pgvector ◀── one-shot Playwright scraper
```

### Backend (`backend/app/`)

- **`main.py`** — FastAPI app with a single `POST /api/chat` endpoint returning `text/event-stream`. The lifespan hook calls `init_pool()` on startup.
- **`db.py`** — Manages the `asyncpg` connection pool. On startup it opens a *plain* connection, runs all SQL migrations in `migrations/`, then creates the pool with `init=_init_connection` (which registers the pgvector codec per-connection). This ordering is critical: `register_vector` introspects the `vector` type and will fail if the `CREATE EXTENSION IF NOT EXISTS vector` migration hasn't run yet.
- **`agent/graph.py`** — A two-node LangGraph `StateGraph`: `model` → conditional edge → `tools` → back to `model`. Compiled and cached with `@lru_cache`.
- **`agent/tools.py`** — Seven `@tool` functions exposed to the LLM. Each returns a JSON-serialisable dict that the SSE layer maps to a named UI component via `TOOL_COMPONENT_KIND` in `main.py`.
- **`agent/prompts.py`** — System prompt. The scope guardrail ("STRICT SCOPE") lives here and instructs the LLM never to call tools for out-of-scope queries.
- **`search/hybrid.py`** — Reciprocal Rank Fusion over two retrieval legs: Postgres `tsvector` FTS (`search_vector` generated column, GIN-indexed) and pgvector cosine similarity over `part_chunks.embedding`. `RRF_K = 60`.

### Database schema (`backend/migrations/001_schema.sql`)

Idempotent (`IF NOT EXISTS` throughout). Key tables:
- `parts` — core part records with a generated `search_vector` (`tsvector`) column weighted A/A/B/C (ps_number, mfg_part_number, name, description).
- `models` — appliance models; `common_symptoms` stored as JSONB.
- `model_parts` — compatibility join between parts and models.
- `part_chunks` — one row per embeddable text chunk (`description`, `install`, `qa`, `symptom`); `embedding vector(1536)` with an IVFFlat cosine index (`lists=100`).
- `part_symptoms`, `part_qa`, `diagrams` — normalised satellite tables.

### Scraper (`scraper/`)

Playwright-driven Chromium crawl (single concurrent page, polite random delays). Entry: `run.py` → `crawl()` generator in `spider.py` → `parse.py` for extraction → `pipeline.py` for DB upsert + embedding generation.

Scope locks:
- Seeded from `/Refrigerator-Models.htm` and `/Dishwasher-Models.htm` only.
- `extract_links` in `parse.py` only follows hrefs matching `*-Refrigerator-Models.htm`, `*-Dishwasher-Models.htm`, `/Models/`, or `/PS\d+`.
- Breadcrumb validation in `parse_model_page` / `parse_part_page` drops any record missing "Refrigerator" or "Dishwasher" in the breadcrumb trail.
- `robots.py` enforces `robots.txt` compliance; scraper bails if a URL is disallowed.

### SSE event contract (`POST /api/chat`)

Events are newline-delimited `data: <json>\n\n` lines:

| type | fields |
|---|---|
| `token` | `delta` |
| `tool_start` | `name`, `args` |
| `component` | `kind`, `data` |
| `done` | — |
| `error` | `message` |

`component.kind` maps to a UI widget: `product_card`, `install_steps`, `compatibility`, `exploded_view`, `escalation`.

### Frontend (`frontend/`)

Next.js + TypeScript scaffold. `lib/useSSE.ts` parses the SSE stream and exposes `{ messages, components, streaming, send }`. The `page.tsx` renders component events as raw JSON; rich PartSelect-themed cards and install visualisers are a planned follow-up.

## Key constraints

- **Scope lock is dual-layered**: system prompt (LLM refuses out-of-scope) + scraper breadcrumb validation (DB only ever contains Refrigerator/Dishwasher records).
- **Scraper is one-shot**: re-running it upserts, but page caps (`SCRAPE_MAX_MODELS`, `SCRAPE_MAX_PARTS`) apply each run. PartSelect blocks plain HTTP; the scraper needs a real browser and may need a non-blocked network.
- **Migration ordering**: always run migrations on a plain connection before creating the pool. Do not move `apply_migrations` after `create_pool` or the `vector` extension check will fail.
- **`gpt-5.4-mini`**: verify this model ID is available in your OpenAI account before deploying; it is configurable via `LLM_MODEL` in `.env`.
