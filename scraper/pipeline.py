"""Clean scraped records, embed unstructured text, and upsert into Postgres."""

import os

import asyncpg
from openai import AsyncOpenAI
from pgvector.asyncpg import register_vector

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://partselect:partselect@db:5432/partselect")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=DATABASE_URL, min_size=1, max_size=4, init=register_vector
    )


async def ensure_schema(pool: asyncpg.Pool) -> None:
    path = os.getenv("MIGRATIONS_PATH", "/app/migrations/001_schema.sql")
    if os.path.exists(path):
        with open(path) as f:
            async with pool.acquire() as conn:
                await conn.execute(f.read())


async def _embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = await _openai.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    return " ".join(text.split()).strip() or None


async def upsert_part(pool: asyncpg.Pool, rec: dict) -> None:
    async with pool.acquire() as conn:
        part_id = await conn.fetchval(
            """
            INSERT INTO parts (ps_number, mfg_part_number, name, appliance_type,
                               price, stock_status, description, install_instructions, url)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (ps_number) DO UPDATE SET
                mfg_part_number = EXCLUDED.mfg_part_number,
                name = EXCLUDED.name,
                appliance_type = EXCLUDED.appliance_type,
                price = EXCLUDED.price,
                stock_status = EXCLUDED.stock_status,
                description = EXCLUDED.description,
                install_instructions = EXCLUDED.install_instructions,
                url = EXCLUDED.url
            RETURNING id
            """,
            rec["ps_number"], _clean(rec.get("mfg_part_number")), _clean(rec["name"]),
            rec["appliance_type"], rec.get("price"), _clean(rec.get("stock_status")),
            _clean(rec.get("description")), _clean(rec.get("install_instructions")),
            rec.get("url"),
        )

        # Replace child rows for idempotency.
        await conn.execute("DELETE FROM part_symptoms WHERE part_id=$1", part_id)
        await conn.execute("DELETE FROM part_qa WHERE part_id=$1", part_id)
        await conn.execute("DELETE FROM part_chunks WHERE part_id=$1", part_id)

        for sym in dict.fromkeys(rec.get("symptoms") or []):
            await conn.execute(
                "INSERT INTO part_symptoms(part_id, symptom) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                part_id, _clean(sym),
            )
        for qa in rec.get("qa") or []:
            await conn.execute(
                "INSERT INTO part_qa(part_id, question, answer) VALUES ($1,$2,$3)",
                part_id, _clean(qa.get("question")), _clean(qa.get("answer")),
            )

        # Build embeddable chunks.
        chunks: list[tuple[str, str]] = []
        if rec.get("description"):
            chunks.append(("description", _clean(rec["description"])))
        if rec.get("install_instructions"):
            chunks.append(("install", _clean(rec["install_instructions"])))
        for sym in rec.get("symptoms") or []:
            if _clean(sym):
                chunks.append(("symptom", _clean(sym)))
        for qa in rec.get("qa") or []:
            text = _clean(f"{qa.get('question','')} {qa.get('answer','')}")
            if text:
                chunks.append(("qa", text))

        if chunks:
            embeddings = await _embed([c[1] for c in chunks])
            for (ctype, content), emb in zip(chunks, embeddings):
                await conn.execute(
                    "INSERT INTO part_chunks(part_id, chunk_type, content, embedding) VALUES ($1,$2,$3,$4)",
                    part_id, ctype, content, emb,
                )


async def upsert_model(pool: asyncpg.Pool, rec: dict) -> None:
    import json

    async with pool.acquire() as conn:
        model_id = await conn.fetchval(
            """
            INSERT INTO models (model_number, appliance_type, name, common_symptoms, url)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (model_number) DO UPDATE SET
                appliance_type = EXCLUDED.appliance_type,
                name = EXCLUDED.name,
                common_symptoms = EXCLUDED.common_symptoms,
                url = EXCLUDED.url
            RETURNING id
            """,
            rec["model_number"], rec["appliance_type"], _clean(rec.get("name")),
            json.dumps(rec.get("common_symptoms") or []), rec.get("url"),
        )
        await conn.execute("DELETE FROM diagrams WHERE model_id=$1", model_id)
        for d in rec.get("diagrams") or []:
            await conn.execute(
                "INSERT INTO diagrams(model_id, name, image_url, section) VALUES ($1,$2,$3,$4)",
                model_id, _clean(d.get("name")), d.get("image_url"), d.get("section"),
            )


async def link_compatibility(pool: asyncpg.Pool, pairs: list[tuple[str, str]]) -> None:
    """Resolve (model_number, ps_number) pairs into model_parts after all rows exist."""
    async with pool.acquire() as conn:
        for model_number, ps_number in pairs:
            await conn.execute(
                """
                INSERT INTO model_parts (model_id, part_id)
                SELECT m.id, p.id FROM models m, parts p
                WHERE m.model_number = $1 AND p.ps_number = $2
                ON CONFLICT DO NOTHING
                """,
                model_number, ps_number,
            )
