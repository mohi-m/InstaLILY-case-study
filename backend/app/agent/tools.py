"""Agent tools — one tool per meaningful data-model capability.

Removed: get_exploded_view (diagrams table absent from schema),
         check_stock_and_price (folded into search_part_by_sku).
Added:   get_model_info, list_parts_for_model,
         search_model_qa, find_symptoms_for_model.
"""

import re
from typing import Any

from langchain_core.tools import tool

from app.db import get_pool
from app.search.embeddings import embed_query
from app.search.hybrid import hybrid_search

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PART_COLS = """id, ps_number, mfg_part_number, name, brand, appliance_type,
                price, stock_status, description, install_instructions,
                install_difficulty, install_time, image_url, url"""


async def _fetch_part(sku: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        f"SELECT {_PART_COLS} FROM parts WHERE ps_number ILIKE $1 OR mfg_part_number ILIKE $1",
        sku.strip(),
    )
    return dict(row) if row else None


async def _fetch_model(model_number: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, model_number, brand, appliance_type, name, url FROM models WHERE model_number ILIKE $1",
        model_number.strip(),
    )
    return dict(row) if row else None


_READMORE_RE = re.compile(r"\s*\bRead (?:more|less)\b\s*", re.IGNORECASE)


def _repair_stories(text: str | None) -> list[str]:
    """install_instructions is scraped customer repair stories joined by blank
    lines — free-form narratives, not numbered steps. Split them back apart and
    strip the "Read more"/"Read less" toggle artifacts left over from scraping."""
    if not text:
        return []
    stories: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        cleaned = _READMORE_RE.sub(" ", block)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) > 8:
            stories.append(cleaned)
    return stories


# ---------------------------------------------------------------------------
# Part lookup
# ---------------------------------------------------------------------------

@tool
async def search_part_by_sku(sku: str) -> dict[str, Any]:
    """Look up a part by its PartSelect number (e.g. PS11752778) or manufacturer
    part number. Returns full part data including price and stock status.
    Use whenever the customer provides a specific part number."""
    part = await _fetch_part(sku)
    if not part:
        return {"found": False, "sku": sku}
    return {"found": True, "part": part}


@tool
async def search_by_symptom(query: str, appliance_type: str | None = None) -> dict[str, Any]:
    """Find parts that fix a described problem or symptom (e.g. 'ice maker not
    working', 'dishes not cleaning'). Optionally restrict to 'Refrigerator' or
    'Dishwasher'. Uses hybrid full-text + semantic search."""
    parts = await hybrid_search(query, appliance_type=appliance_type, limit=5)
    return {"query": query, "count": len(parts), "parts": parts}


@tool
async def get_part_detail(ps_number: str) -> dict[str, Any]:
    """Get full detail for a part: description, symptoms it fixes (with effectiveness
    scores), user-submitted installation steps, and relevant customer Q&A."""
    part = await _fetch_part(ps_number)
    if not part:
        return {"found": False, "ps_number": ps_number}

    pool = get_pool()
    symptoms = await pool.fetch(
        """SELECT s.name, sp.effectiveness
           FROM symptoms s
           JOIN symptom_parts sp ON sp.symptom_id = s.id
           WHERE sp.part_id = $1
           ORDER BY sp.effectiveness DESC NULLS LAST""",
        part["id"],
    )
    qa = await pool.fetch(
        """SELECT q.question, q.answer
           FROM model_qa q
           JOIN qa_parts qp ON qp.qa_id = q.id
           WHERE qp.part_id = $1
           LIMIT 10""",
        part["id"],
    )
    return {
        "found": True,
        "part": part,
        "repair_stories": _repair_stories(part.get("install_instructions")),
        "symptoms": [{"name": r["name"], "effectiveness": r["effectiveness"]} for r in symptoms],
        "qa": [dict(r) for r in qa],
    }


# ---------------------------------------------------------------------------
# Model lookup
# ---------------------------------------------------------------------------

@tool
async def get_model_info(model_number: str) -> dict[str, Any]:
    """Get details about an appliance model: brand, appliance type, name, and
    how many compatible parts are available. Use when a customer mentions a
    model number and you need to establish what appliance they have."""
    model = await _fetch_model(model_number)
    if not model:
        return {"found": False, "model_number": model_number}

    pool = get_pool()
    part_count = await pool.fetchval(
        "SELECT COUNT(*) FROM model_parts WHERE model_id = $1", model["id"]
    )
    return {"found": True, "model": model, "compatible_part_count": part_count}


@tool
async def list_parts_for_model(model_number: str) -> dict[str, Any]:
    """List all parts that are compatible with a specific appliance model number.
    Use when a customer asks 'what parts are available for my [model]?' or wants
    to browse replaceable parts for their appliance."""
    model = await _fetch_model(model_number)
    if not model:
        return {"found": False, "model_number": model_number}

    pool = get_pool()
    rows = await pool.fetch(
        """SELECT p.ps_number, p.mfg_part_number, p.name, p.brand,
                  p.price, p.stock_status, p.image_url, p.url
           FROM parts p
           JOIN model_parts mp ON mp.part_id = p.id
           WHERE mp.model_id = $1
           ORDER BY p.name
           LIMIT 40""",
        model["id"],
    )
    return {
        "found": True,
        "model_number": model["model_number"],
        "appliance_type": model["appliance_type"],
        "count": len(rows),
        "parts": [dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------

@tool
async def check_compatibility(ps_number: str, model_number: str) -> dict[str, Any]:
    """Check whether a part is compatible with a specific appliance model number
    (e.g. WDT780SAEM1). Provide both a PartSelect/manufacturer part number and
    the model number."""
    part = await _fetch_part(ps_number)
    model = await _fetch_model(model_number)

    if not part:
        return {"compatible": None, "reason": "part_not_found", "ps_number": ps_number}
    if not model:
        return {"compatible": None, "reason": "model_not_found", "model_number": model_number}

    pool = get_pool()
    linked = await pool.fetchval(
        "SELECT 1 FROM model_parts WHERE part_id = $1 AND model_id = $2",
        part["id"], model["id"],
    )
    return {
        "compatible": bool(linked),
        "ps_number": part["ps_number"],
        "part_name": part["name"],
        "model_number": model["model_number"],
        "model_name": model["name"],
    }


# ---------------------------------------------------------------------------
# Symptom & Q&A semantic search (leverages the stored embeddings)
# ---------------------------------------------------------------------------

@tool
async def find_symptoms_for_model(model_number: str, symptom_query: str) -> dict[str, Any]:
    """Semantically search symptoms recorded for a specific appliance model, then
    return the parts known to fix each matched symptom along with their
    effectiveness scores. Use when a customer describes a problem AND gives a
    model number."""
    model = await _fetch_model(model_number)
    if not model:
        return {"found": False, "model_number": model_number}

    pool = get_pool()
    embedding = await embed_query(symptom_query)
    symptom_rows = await pool.fetch(
        """SELECT id, name
           FROM symptoms
           WHERE model_id = $1 AND name_embedding IS NOT NULL
           ORDER BY name_embedding <=> $2
           LIMIT 5""",
        model["id"], embedding,
    )
    if not symptom_rows:
        return {"found": True, "model_number": model["model_number"], "symptoms": []}

    results = []
    for s in symptom_rows:
        parts = await pool.fetch(
            """SELECT p.ps_number, p.name, p.price, p.stock_status, sp.effectiveness
               FROM parts p
               JOIN symptom_parts sp ON sp.part_id = p.id
               WHERE sp.symptom_id = $1
               ORDER BY sp.effectiveness DESC NULLS LAST
               LIMIT 5""",
            s["id"],
        )
        results.append({
            "symptom": s["name"],
            "parts": [dict(p) for p in parts],
        })

    return {"found": True, "model_number": model["model_number"], "symptoms": results}


@tool
async def search_model_qa(model_number: str, question: str) -> dict[str, Any]:
    """Semantically search the Q&A database for a specific appliance model.
    Use when a customer asks a how-to or troubleshooting question AND provides
    a model number — this surfaces answers from real customer questions for
    that exact model."""
    model = await _fetch_model(model_number)
    if not model:
        return {"found": False, "model_number": model_number}

    pool = get_pool()
    embedding = await embed_query(question)
    rows = await pool.fetch(
        """SELECT question, answer
           FROM model_qa
           WHERE model_id = $1 AND question_embedding IS NOT NULL
           ORDER BY question_embedding <=> $2
           LIMIT 5""",
        model["id"], embedding,
    )
    return {
        "found": True,
        "model_number": model["model_number"],
        "results": [dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

@tool
async def escalate_to_human(reason: str) -> dict[str, Any]:
    """Hand the conversation to a human support agent. Use when the customer
    explicitly asks for a person or when you cannot resolve their issue with
    the available tools."""
    return {
        "escalated": True,
        "reason": reason,
        "message": "I'm connecting you with a PartSelect support specialist.",
    }


# ---------------------------------------------------------------------------

ALL_TOOLS = [
    search_part_by_sku,
    search_by_symptom,
    get_part_detail,
    get_model_info,
    list_parts_for_model,
    check_compatibility,
    find_symptoms_for_model,
    search_model_qa,
    escalate_to_human,
]
