"""Targeted per-model crawl: model page -> parts listing -> symptom pages."""

import logging

from browser import BrowserPool
from parse import parse_model_page, parse_parts_listing, parse_symptom_page

logger = logging.getLogger(__name__)

BASE = "https://www.partselect.com"
MAX_PARTS = 20


async def collect_parts(browser: BrowserPool, model_number: str, limit: int = MAX_PARTS):
    """Paginate /Models/{M}/Parts/ collecting up to `limit` unique (ps, url) pairs."""
    url = f"{BASE}/Models/{model_number}/Parts/"
    ps_numbers: list[str] = []
    part_urls: list[str] = []
    seen: set[str] = set()
    page_num = 0
    while url and len(ps_numbers) < limit:
        page_num += 1
        logger.debug("  [%s] parts listing page %d: %s", model_number, page_num, url)
        html = await browser.fetch(url)
        if not html:
            logger.warning("  [%s] failed to fetch parts listing page %d", model_number, page_num)
            break
        parsed = parse_parts_listing(html)
        for ps, purl in zip(parsed["ps_numbers"], parsed["part_urls"]):
            if ps in seen:
                continue
            seen.add(ps)
            ps_numbers.append(ps)
            part_urls.append(purl)
            if len(ps_numbers) >= limit:
                break
        url = parsed["next_url"]
    logger.debug("  [%s] collected %d part(s) across %d page(s)", model_number, len(ps_numbers), page_num)
    return ps_numbers[:limit], part_urls[:limit]


async def scrape_model(browser: BrowserPool, model_number: str, appliance_type: str) -> dict:
    """Fetch everything for one model. Returns a blob consumed by run.py."""
    model_url = f"{BASE}/Models/{model_number}/"
    logger.info("[%s] scraping model page", model_number)
    html = await browser.fetch(model_url)
    if not html:
        logger.warning("[%s] model page returned no HTML — using empty defaults", model_number)
    model_rec = parse_model_page(html, model_url) if html else {"qa": [], "symptom_links": []}
    model_rec["url"] = model_url

    ps_numbers, part_urls = await collect_parts(browser, model_number)
    logger.info("[%s] %d compatible part(s) found", model_number, len(ps_numbers))

    symptoms: list[dict] = []
    for link in model_rec.get("symptom_links", []):
        logger.debug("  [%s] fetching symptom page: %s", model_number, link["url"])
        shtml = await browser.fetch(link["url"])
        if not shtml:
            logger.warning("  [%s] failed to fetch symptom '%s'", model_number, link["name"])
        parts = parse_symptom_page(shtml) if shtml else []
        symptoms.append({"name": link["name"], "url": link["url"], "parts": parts})

    logger.info("[%s] done — %d symptom(s), %d Q&A", model_number, len(symptoms), len(model_rec.get("qa", [])))

    return {
        "model_number": model_number,
        "appliance_type": appliance_type,
        "model_rec": model_rec,
        "compat_ps": ps_numbers,
        "compat_urls": part_urls,
        "symptoms": symptoms,
        "qa": model_rec.get("qa", []),
    }
