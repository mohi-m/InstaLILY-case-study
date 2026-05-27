"""Hybrid retrieval: Postgres FTS + pgvector, merged with Reciprocal Rank Fusion."""

from typing import Any

from app.db import get_pool
from app.search.embeddings import embed_query

RRF_K = 60


def _rrf_fuse(
    fts_ids: list[int], vec_ids: list[int], k: int = RRF_K
) -> list[int]:
    scores: dict[int, float] = {}
    for rank, pid in enumerate(fts_ids):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank + 1)
    for rank, pid in enumerate(vec_ids):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda pid: scores[pid], reverse=True)


async def _fts_part_ids(query: str, appliance_type: str | None, limit: int) -> list[int]:
    pool = get_pool()
    sql = """
        SELECT id
        FROM parts
        WHERE search_vector @@ websearch_to_tsquery('english', $1)
          AND ($2::text IS NULL OR appliance_type = $2)
        ORDER BY ts_rank(search_vector, websearch_to_tsquery('english', $1)) DESC
        LIMIT $3
    """
    rows = await pool.fetch(sql, query, appliance_type, limit)
    return [r["id"] for r in rows]


async def _vector_part_ids(
    query: str, appliance_type: str | None, limit: int
) -> list[int]:
    pool = get_pool()
    embedding = await embed_query(query)
    # Rank distinct parts by their best (smallest cosine distance) chunk.
    sql = """
        SELECT c.part_id AS id, MIN(c.embedding <=> $1) AS dist
        FROM part_chunks c
        JOIN parts p ON p.id = c.part_id
        WHERE c.embedding IS NOT NULL
          AND ($2::text IS NULL OR p.appliance_type = $2)
        GROUP BY c.part_id
        ORDER BY dist ASC
        LIMIT $3
    """
    rows = await pool.fetch(sql, embedding, appliance_type, limit)
    return [r["id"] for r in rows]


async def _load_parts(ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, ps_number, mfg_part_number, name, brand, appliance_type,
               price, stock_status, description, url
        FROM parts WHERE id = ANY($1::bigint[])
        """,
        ids,
    )
    by_id = {r["id"]: {**dict(r), "symptoms": []} for r in rows}
    sym_rows = await pool.fetch(
        "SELECT part_id, symptom FROM part_symptoms WHERE part_id = ANY($1::bigint[])",
        ids,
    )
    for r in sym_rows:
        if r["part_id"] in by_id:
            by_id[r["part_id"]]["symptoms"].append(r["symptom"])
    return [by_id[i] for i in ids if i in by_id]


async def hybrid_search(
    query: str,
    appliance_type: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return parts ranked by RRF over FTS and vector retrieval."""
    pool_limit = limit * 4
    fts_ids = await _fts_part_ids(query, appliance_type, pool_limit)
    vec_ids = await _vector_part_ids(query, appliance_type, pool_limit)
    fused = _rrf_fuse(fts_ids, vec_ids)[:limit]
    return await _load_parts(fused)
