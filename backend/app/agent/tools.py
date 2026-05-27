"""Agent tools. Each returns a JSON-serialisable dict that both informs the LLM
and drives a rich UI component via the SSE `component` event."""

from typing import Any

from langchain_core.tools import tool

from app.db import get_pool
from app.search.hybrid import hybrid_search

_PART_COLUMNS = """id, ps_number, mfg_part_number, name, brand, appliance_type,
                   price, stock_status, description, install_instructions,
                   install_difficulty, install_time, image_url, url"""


def _split_steps(text: str | None) -> list[str]:
    if not text:
        return []
    # Strip only surrounding whitespace and decoration chars; preserve leading digits
    # so "1. Disconnect the water line" stays intact.
    lines = [line.strip().lstrip("-•\t") for line in text.splitlines()]
    # Drop very short lines (headers, noise) but keep numbered step fragments
    return [l for l in lines if l and len(l) > 8]


async def _fetch_part(ps_number: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        f"""SELECT {_PART_COLUMNS} FROM parts
            WHERE ps_number ILIKE $1 OR mfg_part_number ILIKE $1""",
        ps_number.strip(),
    )
    return dict(row) if row else None


@tool
async def search_part_by_sku(sku: str) -> dict[str, Any]:
    """Look up a part by its PartSelect number (e.g. PS11752778) or manufacturer
    part number. Use this whenever the customer gives a specific part number."""
    part = await _fetch_part(sku)
    if not part:
        return {"found": False, "sku": sku}
    return {"found": True, "part": part}


@tool
async def search_by_symptom(query: str, appliance_type: str | None = None) -> dict[str, Any]:
    """Find parts that fix a described problem or symptom (e.g. "ice maker not
    working"). Optionally restrict to 'Refrigerator' or 'Dishwasher'.
    Each result includes the symptoms the part is known to fix so you can
    explain the relevance to the customer."""
    parts = await hybrid_search(query, appliance_type=appliance_type, limit=5)
    return {"query": query, "count": len(parts), "parts": parts}


@tool
async def get_part_detail(ps_number: str) -> dict[str, Any]:
    """Get full detail for a part including description, the symptoms it fixes,
    user-submitted installation steps, and customer Q&A."""
    part = await _fetch_part(ps_number)
    if not part:
        return {"found": False, "ps_number": ps_number}
    pool = get_pool()
    symptoms = await pool.fetch(
        """
        SELECT s.name, sp.effectiveness
        FROM symptoms s
        JOIN symptom_parts sp ON sp.symptom_id = s.id
        WHERE sp.part_id = $1
        ORDER BY sp.effectiveness DESC NULLS LAST
        """,
        part["id"],
    )
    qa = await pool.fetch(
        """
        SELECT q.question, q.answer
        FROM model_qa q
        JOIN qa_parts qp ON qp.qa_id = q.id
        WHERE qp.part_id = $1
        LIMIT 10
        """,
        part["id"],
    )
    return {
        "found": True,
        "part": part,
        "install_steps": _split_steps(part.get("install_instructions")),
        "symptoms": [r["name"] for r in symptoms],
        "qa": [dict(r) for r in qa],
    }


@tool
async def check_compatibility(ps_number: str, model_number: str) -> dict[str, Any]:
    """Check whether a part (by PartSelect/manufacturer number) is compatible with a
    specific appliance model number (e.g. WDT780SAEM1)."""
    pool = get_pool()
    part = await _fetch_part(ps_number)
    model = await pool.fetchrow(
        "SELECT id, model_number, brand, appliance_type, name FROM models WHERE model_number ILIKE $1",
        model_number.strip(),
    )
    if not part:
        return {"compatible": None, "reason": "part_not_found", "ps_number": ps_number}
    if not model:
        return {"compatible": None, "reason": "model_not_found", "model_number": model_number}
    linked = await pool.fetchval(
        "SELECT 1 FROM model_parts WHERE part_id = $1 AND model_id = $2",
        part["id"],
        model["id"],
    )
    return {
        "compatible": bool(linked),
        "ps_number": part["ps_number"],
        "part_name": part["name"],
        "model_number": model["model_number"],
        "model_name": model["name"],
    }


@tool
async def get_exploded_view(model_number: str) -> dict[str, Any]:
    """Get schematic / exploded-view diagram URLs for an appliance model."""
    pool = get_pool()
    model = await pool.fetchrow(
        "SELECT id, model_number, name FROM models WHERE model_number ILIKE $1",
        model_number.strip(),
    )
    if not model:
        return {"found": False, "model_number": model_number}
    diagrams = await pool.fetch(
        "SELECT name, image_url, section FROM diagrams WHERE model_id = $1", model["id"]
    )
    return {
        "found": True,
        "model_number": model["model_number"],
        "diagrams": [dict(d) for d in diagrams],
    }


@tool
async def check_stock_and_price(ps_number: str) -> dict[str, Any]:
    """Get the current stock status and price for a part."""
    part = await _fetch_part(ps_number)
    if not part:
        return {"found": False, "ps_number": ps_number}
    return {
        "found": True,
        "ps_number": part["ps_number"],
        "name": part["name"],
        "price": part["price"],
        "stock_status": part["stock_status"],
        "part": part,
    }


@tool
async def escalate_to_human(reason: str) -> dict[str, Any]:
    """Hand the conversation to a human support agent. Use when the customer asks for
    a person or when you cannot resolve their issue."""
    return {
        "escalated": True,
        "reason": reason,
        "message": "I'm connecting you with a PartSelect support specialist.",
    }


ALL_TOOLS = [
    search_part_by_sku,
    search_by_symptom,
    get_part_detail,
    check_compatibility,
    get_exploded_view,
    check_stock_and_price,
    escalate_to_human,
]
