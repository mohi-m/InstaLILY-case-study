"""One-shot entrypoint: crawl PartSelect, embed, and load Postgres.

Usage (from compose):  docker compose run --rm scraper python run.py
Re-running is safe (idempotent upserts), but per the design this is meant to run once.
"""

import asyncio
import logging

from pipeline import (
    ensure_schema,
    get_pool,
    link_compatibility,
    upsert_model,
    upsert_part,
)
from spider import crawl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


async def main() -> None:
    log.info("Starting PartSelect scrape pipeline")
    pool = await get_pool()
    await ensure_schema(pool)

    models = parts = 0
    # Collect compatibility pairs and link after all rows exist to avoid FK misses.
    compatibility: list[tuple[str, str]] = []

    async for kind, record in crawl():
        if kind == "model":
            await upsert_model(pool, record)
            for ps in record.get("compatible_ps", []):
                compatibility.append((record["model_number"], ps))
            models += 1
            log.info("[model] %s (%s)", record["model_number"], record["appliance_type"])
        elif kind == "part":
            await upsert_part(pool, record)
            parts += 1
            log.info("[part]  %s (%s)", record["ps_number"], record["appliance_type"])

    # Link compatibility only after all parts/models are loaded.
    log.info("Linking %d compatibility pairs", len(compatibility))
    await link_compatibility(pool, compatibility)
    await pool.close()
    log.info("Done. Loaded %d models, %d parts, %d compat links.", models, parts, len(compatibility))


if __name__ == "__main__":
    asyncio.run(main())
