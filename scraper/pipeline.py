"""Clean scraped records, embed unstructured text, and upsert into Postgres."""

import os
from pathlib import Path

import asyncpg
from openai import AsyncOpenAI
from pgvector.asyncpg import register_vector

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://partselect:partselect@localhost:5432/partselect"
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=4, init=register_vector)


def _migrations_dir() -> Path | None:
    candidates = [
        os.getenv("MIGRATIONS_DIR"),
        "migrations",
        str(Path(__file__).resolve().parent.parent / "backend" / "migrations"),
    ]
    for c in candidates:
        if c and Path(c).is_dir():
            return Path(c)
    return None


async def ensure_schema(pool: asyncpg.Pool) -> None:
    mig = _migrations_dir()
    if not mig:
        return
    async with pool.acquire() as conn:
        for sql_file in sorted(mig.glob("*.sql")):
            await conn.execute(sql_file.read_text())


async def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = await _openai.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    return " ".join(text.split()).strip() or None


# --------------------------------------------------------------------------- parts


async def upsert_part(pool: asyncpg.Pool, rec: dict, appliance_type: str) -> int:
    symptom_text = ", ".join(rec.get("symptoms") or []) or None
    async with pool.acquire() as conn:
        part_id = await conn.fetchval(
            """
            INSERT INTO parts (ps_number, mfg_part_number, name, brand, appliance_type,
                               price, stock_status, description, install_instructions,
                               install_difficulty, install_time, image_url, url, symptom_text)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (ps_number) DO UPDATE SET
                mfg_part_number = EXCLUDED.mfg_part_number,
                name = EXCLUDED.name,
                brand = COALESCE(EXCLUDED.brand, parts.brand),
                appliance_type = EXCLUDED.appliance_type,
                price = EXCLUDED.price,
                stock_status = EXCLUDED.stock_status,
                description = EXCLUDED.description,
                install_instructions = EXCLUDED.install_instructions,
                install_difficulty = EXCLUDED.install_difficulty,
                install_time = EXCLUDED.install_time,
                image_url = EXCLUDED.image_url,
                url = EXCLUDED.url,
                symptom_text = EXCLUDED.symptom_text
            RETURNING id
            """,
            rec["ps_number"], _clean(rec.get("mfg_part_number")), _clean(rec["name"]),
            _clean(rec.get("brand")), appliance_type, rec.get("price"),
            _clean(rec.get("stock_status")), _clean(rec.get("description")),
            _clean(rec.get("install_instructions")), _clean(rec.get("install_difficulty")),
            _clean(rec.get("install_time")), rec.get("image_url"),
            rec.get("url"), symptom_text,
        )

        await conn.execute("DELETE FROM part_chunks WHERE part_id=$1", part_id)
        chunks: list[tuple[str, str]] = []
        if rec.get("description"):
            chunks.append(("description", _clean(rec["description"])))
        if rec.get("install_instructions"):
            chunks.append(("install", _clean(rec["install_instructions"])))
        for sym in rec.get("symptoms") or []:
            if _clean(sym):
                chunks.append(("symptom", _clean(sym)))
        if chunks:
            embeddings = await embed([c[1] for c in chunks])
            for (ctype, content), emb in zip(chunks, embeddings):
                await conn.execute(
                    "INSERT INTO part_chunks(part_id, chunk_type, content, embedding) "
                    "VALUES ($1,$2,$3,$4)",
                    part_id, ctype, content, emb,
                )
    return part_id


# --------------------------------------------------------------------------- models


async def upsert_model(pool: asyncpg.Pool, model_number: str, appliance_type: str, rec: dict) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO models (model_number, brand, appliance_type, name, url)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (model_number) DO UPDATE SET
                brand = COALESCE(EXCLUDED.brand, models.brand),
                appliance_type = EXCLUDED.appliance_type,
                name = EXCLUDED.name,
                url = EXCLUDED.url
            RETURNING id
            """,
            model_number, _clean(rec.get("brand")), appliance_type,
            _clean(rec.get("name")), rec.get("url"),
        )


async def link_compatibility(pool: asyncpg.Pool, model_id: int, ps_numbers: list[str]) -> None:
    async with pool.acquire() as conn:
        for ps in ps_numbers:
            await conn.execute(
                """
                INSERT INTO model_parts (model_id, part_id)
                SELECT $1, p.id FROM parts p WHERE p.ps_number = $2
                ON CONFLICT DO NOTHING
                """,
                model_id, ps,
            )


# --------------------------------------------------------------------------- symptoms


async def upsert_symptoms(pool: asyncpg.Pool, model_id: int, symptoms: list[dict]) -> dict[str, int]:
    """Insert symptoms (with name embeddings) for a model; return {name: symptom_id}."""
    if not symptoms:
        return {}
    names = [_clean(s["name"]) for s in symptoms if _clean(s.get("name"))]
    embeddings = await embed(names)
    result: dict[str, int] = {}
    async with pool.acquire() as conn:
        for s, emb in zip([s for s in symptoms if _clean(s.get("name"))], embeddings):
            name = _clean(s["name"])
            sid = await conn.fetchval(
                """
                INSERT INTO symptoms (model_id, name, url, name_embedding)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT (model_id, name) DO UPDATE SET
                    url = EXCLUDED.url, name_embedding = EXCLUDED.name_embedding
                RETURNING id
                """,
                model_id, name, s.get("url"), emb,
            )
            await conn.execute("DELETE FROM symptom_parts WHERE symptom_id=$1", sid)
            result[name] = sid
    return result


async def upsert_symptom_parts(pool: asyncpg.Pool, symptom_id: int, parts: list[dict]) -> None:
    async with pool.acquire() as conn:
        for p in parts:
            await conn.execute(
                """
                INSERT INTO symptom_parts (symptom_id, part_id, effectiveness)
                SELECT $1, pa.id, $3 FROM parts pa WHERE pa.ps_number = $2
                ON CONFLICT (symptom_id, part_id)
                DO UPDATE SET effectiveness = EXCLUDED.effectiveness
                """,
                symptom_id, p["ps_number"], p.get("effectiveness"),
            )


# --------------------------------------------------------------------------- Q&A


async def upsert_qa(pool: asyncpg.Pool, model_id: int, qa_list: list[dict]) -> None:
    if not qa_list:
        return
    questions = [_clean(q.get("question")) or "" for q in qa_list]
    embeddings = await embed(questions)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM model_qa WHERE model_id=$1", model_id)
        for q, emb in zip(qa_list, embeddings):
            qa_id = await conn.fetchval(
                """
                INSERT INTO model_qa (model_id, question, answer, question_embedding)
                VALUES ($1,$2,$3,$4) RETURNING id
                """,
                model_id, _clean(q.get("question")), _clean(q.get("answer")), emb,
            )
            for part in q.get("parts") or []:
                await conn.execute(
                    """
                    INSERT INTO qa_parts (qa_id, part_id)
                    SELECT $1, p.id FROM parts p WHERE p.ps_number = $2
                    ON CONFLICT DO NOTHING
                    """,
                    qa_id, part["ps"],
                )
