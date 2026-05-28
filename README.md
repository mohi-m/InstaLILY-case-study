# PartSelect Conversational Agent

A conversational AI agent that helps customers find **Refrigerator** and **Dishwasher**
replacement parts, verify model compatibility, troubleshoot symptoms, and get
installation guidance. The agent is **strictly scoped** to these two appliance
categories and politely declines anything else.

## Architecture

```
Next.js (PartSelect UI)  ──SSE──▶  FastAPI  ──▶  LangGraph agent (GPT-5.4-mini, 8 tools)
                                                       │
                                                       ▼
                                   Hybrid search (Postgres FTS + pgvector RRF)
                                                       │
                                                       ▼
                             Postgres 16 + pgvector  ◀── one-shot Playwright scraper
```

- **Backend** (`backend/`): FastAPI, LangGraph `StateGraph`, OpenAI GPT-5.4-mini.
  Tools: `search_by_symptom`, `get_part_detail`, `get_model_info`,
  `list_parts_for_model`, `check_compatibility`, `find_symptoms_for_model`,
  `search_model_qa`, `escalate_to_human`.
- **Search**: exact/keyword via Postgres `tsvector`; semantic troubleshooting via
  pgvector + `text-embedding-3-small`; merged with Reciprocal Rank Fusion.
- **Scraper** (`scraper/`): Playwright-driven Chromium crawl over a fixed list of
  Refrigerator and Dishwasher models (`scraper/targets.py`), robots.txt-respecting.
  **Run once**; re-running is safe (idempotent upserts).
- **Frontend** (`frontend/`): Next.js + TypeScript chat UI consuming the SSE stream,
  rendering tool activity inline and dispatching the agent's component events to
  PartSelect-themed cards (parts, install steps, compatibility, model info, Q&A).

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 22+
- PostgreSQL 16 with [pgvector](https://github.com/pgvector/pgvector)

Create the database and enable pgvector once:

```sql
CREATE DATABASE partselect;
\c partselect
CREATE EXTENSION IF NOT EXISTS vector;
```

### 1. Environment

```bash
cp .env.example .env   # set OPENAI_API_KEY (and DATABASE_URL if credentials differ)
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify: `curl localhost:8000/health` → `{"status":"ok"}`

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

## Sample queries

```bash
curl -N localhost:8000/api/chat -H 'Content-Type: application/json' -d '{
  "messages":[{"role":"user","content":"How can I install part number PS11752778?"}]}'
```

- "How can I install part number PS11752778?" → `get_part_detail` → install-steps card.
- "Is PS11752778 compatible with my WDT780SAEM1 model?" → `check_compatibility`.
- "The ice maker on my Whirlpool fridge is not working." → `search_by_symptom` hybrid search.
- Out-of-scope (e.g. "what's the weather?") → polite refusal, no tool calls.

## SSE event contract

`POST /api/chat` returns `text/event-stream` of JSON events:
`{"type":"token","delta":...}`, `{"type":"tool_start","name":...,"args":...}`,
`{"type":"component","kind":...,"data":...}`, `{"type":"done"}`, `{"type":"error",...}`.

## Tests

```bash
cd backend && pip install -r requirements.txt && pytest
```

Unit tests cover the scraper's HTML parsers (parts listing, symptom page, part page),
RRF ordering for hybrid search, SSE tool-output coercion, and the scope guardrail prompt.
