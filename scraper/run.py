"""One-shot entrypoint: crawl PartSelect, embed, and load Postgres.

Usage (from compose):  docker compose run --rm scraper python run.py
Re-running is safe (idempotent upserts), but per the design this is meant to run once.
"""

import asyncio

from pipeline import (
    ensure_schema,
    get_pool,
    link_compatibility,
    upsert_model,
    upsert_part,
)
from spider import crawl


async def main() -> None:
    pool = await get_pool()
    await ensure_schema(pool)

    models = parts = 0
    compatibility: list[tuple[str, str]] = []

    async for kind, record in crawl():
        if kind == "model":
            await upsert_model(pool, record)
            for ps in record.get("compatible_ps", []):
                compatibility.append((record["model_number"], ps))
            models += 1
            print(f"[model] {record['model_number']} ({record['appliance_type']})")
        elif kind == "part":
            await upsert_part(pool, record)
            parts += 1
            print(f"[part]  {record['ps_number']} ({record['appliance_type']})")

    # Link compatibility only after all parts/models are loaded.
    await link_compatibility(pool, compatibility)
    await pool.close()
    print(f"\nDone. Loaded {models} models, {parts} parts, {len(compatibility)} compat links.")


if __name__ == "__main__":
    asyncio.run(main())
