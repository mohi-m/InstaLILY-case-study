"""One-shot entrypoint: crawl the targeted PartSelect models, embed, load Postgres.

Usage:  python run.py            (scrape all targets)
        SCRAPE_ONLY=WDT780SAEM1 python run.py   (smoke-test a single model)

Re-running is safe (idempotent upserts). Requires a real display — the browser runs
HEADFUL because PartSelect blocks headless Chromium.
"""

import asyncio
import logging
import os

import asyncpg

from dotenv import load_dotenv

from browser import BrowserPool
from parse import parse_part_page
from pipeline import (
    ensure_schema,
    get_pool,
    link_compatibility,
    upsert_model,
    upsert_part,
    upsert_qa,
    upsert_symptom_parts,
    upsert_symptoms,
)
from robots import RobotsGate
from spider import scrape_model
from targets import TARGETS

# Load repo-root .env so OPENAI_API_KEY / DATABASE_URL are available.
load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _select_targets() -> list[tuple[str, str]]:
    only = os.getenv("SCRAPE_ONLY")
    if only:
        wanted = {m.strip() for m in only.split(",")}
        selected = [(m, t) for m, t in TARGETS if m in wanted]
        logger.info("SCRAPE_ONLY filter active — %d of %d targets selected", len(selected), len(TARGETS))
        return selected
    return TARGETS


async def _existing_models(pool: asyncpg.Pool) -> set[str]:
    rows = await pool.fetch("SELECT model_number FROM models")
    return {r["model_number"] for r in rows}


async def main() -> None:
    targets = _select_targets()
    logger.info("Checking robots.txt")
    robots = RobotsGate()
    robots.load()

    pool = await get_pool()
    await ensure_schema(pool)

    existing = await _existing_models(pool)
    targets = [(m, t) for m, t in targets if m not in existing]
    if not targets:
        logger.info("All models already in DB — nothing to scrape.")
        await pool.close()
        return
    logger.info("Skipping %d existing model(s). Scraping %d new model(s): %s",
                len(existing), len(targets), [m for m, _ in targets])

    async with BrowserPool(robots=robots) as browser:
        # Phase 1 — scrape every model page / parts listing / symptom pages.
        logger.info("Phase 1: scraping %d model(s)", len(targets))
        blobs = await asyncio.gather(
            *[scrape_model(browser, m, t) for m, t in targets]
        )

        # Phase 2 — global unique set of parts to fetch (listing + symptom + Q&A refs).
        # setdefault keeps the first URL seen; appliance_type follows suit.
        part_targets: dict[str, dict] = {}  # ps -> {"url", "appliance_type"}

        def add_part(ps: str, url: str | None, appliance_type: str) -> None:
            if not ps or not url:
                return
            part_targets.setdefault(ps, {"url": url, "appliance_type": appliance_type})

        for blob in blobs:
            atype = blob["appliance_type"]
            for ps, url in zip(blob["compat_ps"], blob["compat_urls"]):
                add_part(ps, url, atype)
            for sym in blob["symptoms"]:
                for p in sym["parts"]:
                    add_part(p["ps_number"], p.get("url"), atype)
            for qa in blob["qa"]:
                for p in qa.get("parts", []):
                    add_part(p["ps"], p.get("url"), atype)

        logger.info("Phase 2: %d unique part(s) to fetch across all models", len(part_targets))

        # Phase 3 — fetch + parse each unique part page once.
        ps_list = list(part_targets)

        async def fetch_part(ps: str) -> dict | None:
            html = await browser.fetch(part_targets[ps]["url"])
            return parse_part_page(html, part_targets[ps]["url"]) if html else None

        logger.info("Phase 3: fetching %d part page(s)", len(ps_list))
        part_recs = await asyncio.gather(*[fetch_part(ps) for ps in ps_list])

    # Phase 4 — load parts.
    logger.info("Phase 4: upserting parts into DB")
    loaded_parts = 0
    failed_parts = 0
    for ps, rec in zip(ps_list, part_recs):
        if not rec:
            logger.warning("Parse returned nothing for part %s — skipping", ps)
            failed_parts += 1
            continue
        await upsert_part(pool, rec, part_targets[ps]["appliance_type"])
        loaded_parts += 1
    logger.info("Parts upserted: %d loaded, %d failed/skipped", loaded_parts, failed_parts)

    # Phase 5 — load models, compatibility, symptoms, symptom_parts, Q&A.
    logger.info("Phase 5: upserting models, symptoms, and Q&A into DB")
    models_loaded = symptoms_loaded = qa_loaded = 0
    for blob in blobs:
        model_id = await upsert_model(
            pool, blob["model_number"], blob["appliance_type"], blob["model_rec"]
        )
        models_loaded += 1
        await link_compatibility(pool, model_id, blob["compat_ps"])

        sym_ids = await upsert_symptoms(
            pool, model_id, [{"name": s["name"], "url": s["url"]} for s in blob["symptoms"]]
        )
        symptoms_loaded += len(sym_ids)
        for s in blob["symptoms"]:
            # Normalise whitespace to match the key written by upsert_symptoms.
            sid = sym_ids.get(" ".join(s["name"].split()).strip())
            if sid:
                await upsert_symptom_parts(pool, sid, s["parts"])

        await upsert_qa(pool, model_id, blob["qa"])
        qa_loaded += len(blob["qa"])
        logger.info("[model] %s (%s) parts=%d symptoms=%d qa=%d",
                    blob["model_number"], blob["appliance_type"],
                    len(blob["compat_ps"]), len(blob["symptoms"]), len(blob["qa"]))

    await pool.close()
    logger.info("Done. %d models, %d parts, %d symptoms, %d Q&A loaded.",
                models_loaded, loaded_parts, symptoms_loaded, qa_loaded)


if __name__ == "__main__":
    asyncio.run(main())
