"""One-shot entrypoint: crawl the targeted PartSelect models, embed, load Postgres.

Usage:  python run.py            (scrape all targets)
        SCRAPE_ONLY=WDT780SAEM1 python run.py   (smoke-test a single model)

Re-running is safe (idempotent upserts). Requires a real display — the browser runs
HEADFUL because PartSelect blocks headless Chromium.
"""

import asyncio
import os

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


def _select_targets() -> list[tuple[str, str]]:
    only = os.getenv("SCRAPE_ONLY")
    if only:
        wanted = {m.strip() for m in only.split(",")}
        return [(m, t) for m, t in TARGETS if m in wanted]
    return TARGETS


async def main() -> None:
    targets = _select_targets()
    robots = RobotsGate()
    robots.load()

    pool = await get_pool()
    await ensure_schema(pool)

    async with BrowserPool(robots=robots) as browser:
        # Phase 1 — scrape every model page / parts listing / symptom pages.
        blobs = await asyncio.gather(
            *[scrape_model(browser, m, t) for m, t in targets]
        )

        # Phase 2 — global unique set of parts to fetch (listing + symptom + Q&A refs).
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

        # Phase 3 — fetch + parse each unique part page once.
        ps_list = list(part_targets)

        async def fetch_part(ps: str) -> dict | None:
            html = await browser.fetch(part_targets[ps]["url"])
            return parse_part_page(html, part_targets[ps]["url"]) if html else None

        part_recs = await asyncio.gather(*[fetch_part(ps) for ps in ps_list])

    # Phase 4 — load parts.
    loaded_parts = 0
    for ps, rec in zip(ps_list, part_recs):
        if not rec:
            continue
        await upsert_part(pool, rec, part_targets[ps]["appliance_type"])
        loaded_parts += 1

    # Phase 5 — load models, compatibility, symptoms, symptom_parts, Q&A.
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
            sid = sym_ids.get(" ".join(s["name"].split()).strip())
            if sid:
                await upsert_symptom_parts(pool, sid, s["parts"])

        await upsert_qa(pool, model_id, blob["qa"])
        qa_loaded += len(blob["qa"])
        print(f"[model] {blob['model_number']} ({blob['appliance_type']}) "
              f"parts={len(blob['compat_ps'])} symptoms={len(blob['symptoms'])} qa={len(blob['qa'])}")

    await pool.close()
    print(f"\nDone. {models_loaded} models, {loaded_parts} parts, "
          f"{symptoms_loaded} symptoms, {qa_loaded} Q&A loaded.")


if __name__ == "__main__":
    asyncio.run(main())
