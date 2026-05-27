"""Targeted per-model crawl: model page -> parts listing -> symptom pages."""

from browser import BrowserPool
from parse import parse_model_page, parse_parts_listing, parse_symptom_page

BASE = "https://www.partselect.com"
MAX_PARTS = 20


async def collect_parts(browser: BrowserPool, model_number: str, limit: int = MAX_PARTS):
    """Paginate /Models/{M}/Parts/ collecting up to `limit` unique (ps, url) pairs."""
    url = f"{BASE}/Models/{model_number}/Parts/"
    ps_numbers: list[str] = []
    part_urls: list[str] = []
    seen: set[str] = set()
    while url and len(ps_numbers) < limit:
        html = await browser.fetch(url)
        if not html:
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
    return ps_numbers[:limit], part_urls[:limit]


async def scrape_model(browser: BrowserPool, model_number: str, appliance_type: str) -> dict:
    """Fetch everything for one model. Returns a blob consumed by run.py."""
    model_url = f"{BASE}/Models/{model_number}/"
    html = await browser.fetch(model_url)
    model_rec = parse_model_page(html, model_url) if html else {"qa": [], "symptom_links": []}
    model_rec["url"] = model_url

    ps_numbers, part_urls = await collect_parts(browser, model_number)

    symptoms: list[dict] = []
    for link in model_rec.get("symptom_links", []):
        shtml = await browser.fetch(link["url"])
        parts = parse_symptom_page(shtml) if shtml else []
        symptoms.append({"name": link["name"], "url": link["url"], "parts": parts})

    return {
        "model_number": model_number,
        "appliance_type": appliance_type,
        "model_rec": model_rec,
        "compat_ps": ps_numbers,
        "compat_urls": part_urls,
        "symptoms": symptoms,
        "qa": model_rec.get("qa", []),
    }
