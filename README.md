# PartSelect Conversational Agent

A conversational AI agent that helps customers find **Refrigerator** and **Dishwasher**
replacement parts, verify model compatibility, troubleshoot symptoms, and get
installation guidance. The agent is **strictly scoped** to these two appliance
categories and politely declines anything else.

> **Milestone status — backend-first.** This repo currently delivers the complete,
> demoable backend: Postgres + pgvector, a one-shot Playwright data pipeline, hybrid
> (full-text + vector) search, a LangGraph agent over GPT-5.4-mini, and a FastAPI SSE
> API. The Next.js frontend is a **scaffold** that proves the streaming contract; the
> rich PartSelect-themed UI and in-chat custom components (product cards, exploded-view
> diagrams, install visualizer) are a follow-up.

## Architecture

```
Next.js (scaffold)  ──SSE──▶  FastAPI  ──▶  LangGraph agent (GPT-5.4-mini, 7 tools)
                                                  │
                                                  ▼
                              Hybrid search (Postgres FTS + pgvector RRF)
                                                  │
                                                  ▼
                        Postgres 16 + pgvector  ◀── one-shot Playwright scraper
```

- **Backend** (`backend/`): FastAPI, LangGraph `StateGraph`, OpenAI GPT-5.4-mini.
  Tools: `search_part_by_sku`, `search_by_symptom`, `get_part_detail`,
  `check_compatibility`, `get_exploded_view`, `check_stock_and_price`,
  `escalate_to_human`.
- **Search**: exact/keyword via Postgres `tsvector`; semantic troubleshooting via
  pgvector + `text-embedding-3-small`; merged with Reciprocal Rank Fusion.
- **Scraper** (`scraper/`): Playwright-driven Chromium crawl, scope-locked to
  `*-Refrigerator-Models.htm` / `*-Dishwasher-Models.htm`, breadcrumb-validated,
  robots.txt-respecting. **Run once**; data persists in the `pgdata` volume.
- **Frontend** (`frontend/`): Next.js + TypeScript chat scaffold consuming the SSE
  stream.

## Quick start

```bash
cp .env.example .env        # set OPENAI_API_KEY
docker compose up -d db backend frontend
curl localhost:8000/health  # {"status":"ok"}
```

### Populate the database (run once)

PartSelect blocks plain HTTP requests, so the scraper drives a real browser. It is
profile-gated and does **not** run on `up`:

```bash
docker compose run --rm scraper python run.py
```

If PartSelect hard-blocks the container's IP, run the scraper from an unblocked
network; because data lands in the `pgdata` Docker volume, this is a one-time step.
Page counts are bounded by `SCRAPE_MAX_MODELS` / `SCRAPE_MAX_PARTS` in `.env`.

## Sample queries (work at the API level this milestone)

```bash
curl -N localhost:8000/api/chat -H 'Content-Type: application/json' -d '{
  "messages":[{"role":"user","content":"How can I install part number PS11752778?"}]}'
```

- "How can I install part number PS11752778?" → SKU lookup → install-steps component.
- "Is this part compatible with my WDT780SAEM1 model?" → compatibility check.
- "The ice maker on my Whirlpool fridge is not working. How can I fix it?" → symptom
  hybrid search.
- Out-of-scope (e.g. "what's the weather?") → polite refusal, no tool calls.

## SSE event contract

`POST /api/chat` returns `text/event-stream` of JSON events:
`{"type":"token","delta":...}`, `{"type":"tool_start","name":...,"args":...}`,
`{"type":"component","kind":...,"data":...}`, `{"type":"done"}`, `{"type":"error",...}`.

## Tests

```bash
cd backend && pip install -r requirements.txt && pytest
```

Unit tests cover breadcrumb scope validation, frontier link patterns, RRF ordering,
SSE tool-output coercion, and the scope guardrail prompt.
