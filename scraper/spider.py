"""Scope-locked Playwright crawler for PartSelect Refrigerator/Dishwasher data.

Drives a real Chromium (with stealth) so we get past the anti-bot 403 that plain
HTTP requests hit. Concurrency is 1 with randomised polite delays. Run ONCE; the
results persist in the Postgres volume.
"""

import asyncio
import logging
import os
import random
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from parse import extract_links, parse_model_page, parse_part_page
from robots import USER_AGENT, RobotsGate

log = logging.getLogger(__name__)

BASE = "https://www.partselect.com"
SEEDS = [f"{BASE}/Refrigerator-Models.htm", f"{BASE}/Dishwasher-Models.htm"]

MIN_DELAY = float(os.getenv("SCRAPE_MIN_DELAY", "3"))
MAX_DELAY = float(os.getenv("SCRAPE_MAX_DELAY", "7"))
MAX_MODELS = int(os.getenv("SCRAPE_MAX_MODELS", "40"))
MAX_PARTS = int(os.getenv("SCRAPE_MAX_PARTS", "200"))
MAX_CATEGORY_PAGES = int(os.getenv("SCRAPE_MAX_CATEGORY_PAGES", "60"))
HEADLESS = os.getenv("SCRAPE_HEADLESS", "0") not in ("0", "false", "no")
JS_SETTLE_MS = int(os.getenv("SCRAPE_JS_SETTLE_MS", "2500"))  # ms to wait after page load for JS rendering

# Part-category subcategories — used to build direct part-discovery seed URLs.
# Covering common failure points for Refrigerators and Dishwashers.
_REFRIGERATOR_SUBCATS = [
    "Refrigerator-Door-Gaskets",
    "Refrigerator-Ice-Makers",
    "Refrigerator-Ice-Maker-Parts",
    "Refrigerator-Water-Filters",
    "Refrigerator-Water-Inlet-Valves",
    "Refrigerator-Filters",
    "Refrigerator-Defrost-Heaters",
    "Refrigerator-Defrost-Thermostats",
    "Refrigerator-Evaporator-Fan-Motors",
    "Refrigerator-Temperature-Controls",
    "Refrigerator-Thermistors",
    "Refrigerator-Door-Handles",
    "Refrigerator-Shelves",
    "Refrigerator-Compressors",
    "Refrigerator-Motors",
    "Refrigerator-Dispenser-Parts",
    "Refrigerator-Door-Switches",
    "Refrigerator-Hoses-Tubes",
    "Refrigerator-Valves",
    "Refrigerator-Light-Bulbs",
]

_DISHWASHER_SUBCATS = [
    "Dishwasher-Door-Gaskets",
    "Dishwasher-Drain-Pumps",
    "Dishwasher-Spray-Arms",
    "Dishwasher-Heating-Elements",
    "Dishwasher-Inlet-Valves",
    "Dishwasher-Control-Panels",
    "Dishwasher-Door-Latches",
    "Dishwasher-Filters",
    "Dishwasher-Racks",
    "Dishwasher-Motors",
    "Dishwasher-Door-Hinges",
    "Dishwasher-Float-Switches",
    "Dishwasher-Timers",
    "Dishwasher-Thermostats",
    "Dishwasher-Pumps",
    "Dishwasher-Door-Handles",
]

_BRANDS = [
    "Whirlpool", "GE", "Samsung", "LG", "Frigidaire",
    "Kenmore", "KitchenAid", "Maytag", "Bosch", "Amana",
]

# Pre-seed the model queue with known model numbers (compatible parts are discovered
# from their /Models/{number}/Parts/ listing pages).
_SEED_MODEL_NUMBERS = [
    "WDT780SAEM1",
    "WRS325SDHZ08", "WRF535SWHZ00", "WRX735SDHZ00",
    "GDT695SSJSS", "GSS25GSHSS", "GNE27JSMSS",
    "KDTM354DSS4", "KRMF706ESS01",
    "MDB4949SKZ0", "MFI2570FEZ01",
    "RF28R7351SR", "DW80R5061US",
    "SHPM88Z75N", "LMXS30776S",
]


def _category_seeds() -> list[str]:
    """Build URLs for top-level category, subcategory, and brand×subcategory pages.

    These pages list parts directly (not via models), giving a much wider initial
    set of part URLs than crawling only through model listing pages.
    """
    urls: list[str] = [
        f"{BASE}/Refrigerator-Parts.htm",
        f"{BASE}/Dishwasher-Parts.htm",
    ]
    for sub in _REFRIGERATOR_SUBCATS:
        urls.append(f"{BASE}/{sub}.htm")
    for sub in _DISHWASHER_SUBCATS:
        urls.append(f"{BASE}/{sub}.htm")
    # Top brands × top subcategories (first 6 per appliance type to stay polite)
    for brand in _BRANDS:
        for sub in _REFRIGERATOR_SUBCATS[:6]:
            urls.append(f"{BASE}/{brand}-{sub}.htm")
        for sub in _DISHWASHER_SUBCATS[:6]:
            urls.append(f"{BASE}/{brand}-{sub}.htm")
    return urls


# Cloudflare challenge page markers — if any appear in HTML the real page hasn't loaded yet.
CF_MARKERS = ("Just a moment", "Checking your browser", "cf-challenge")


async def _polite_sleep(robots: RobotsGate) -> None:
    delay = robots.crawl_delay or random.uniform(MIN_DELAY, MAX_DELAY)
    await asyncio.sleep(delay)


async def _fetch(page, url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            # "networkidle" waits for JS-heavy pages to finish rendering; fall back on timeout.
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(JS_SETTLE_MS)
            html = await page.content()
            if any(marker in html for marker in CF_MARKERS):
                wait = 8 * (attempt + 1)
                log.warning("CF challenge on %s; waiting %ds (attempt %d)", url, wait, attempt + 1)
                await asyncio.sleep(wait)
                # Reload after back-off so CF can resolve the challenge.
                try:
                    await page.reload(wait_until="networkidle", timeout=60000)
                    await page.wait_for_timeout(JS_SETTLE_MS)
                    html = await page.content()
                    if not any(marker in html for marker in CF_MARKERS):
                        return html
                except Exception:
                    pass
                continue
            return html
        except Exception as exc:
            wait = 2 ** (attempt + 1)
            log.warning(
                "Fetch error on %s (attempt %d): %s; retrying in %ds",
                url, attempt + 1, exc, wait,
            )
            await asyncio.sleep(wait)
    log.error("Giving up on %s after %d attempts", url, retries)
    return None


async def crawl():
    """Async generator yielding ('model'|'part', record) tuples."""
    robots = RobotsGate(BASE)
    robots.load()

    seen: set[str] = set()
    brand_q: list[str] = list(SEEDS)
    model_q: list[str] = [f"{BASE}/Models/{mn}/Parts/" for mn in _SEED_MODEL_NUMBERS]
    part_q: list[str] = []
    models_done = parts_done = 0

    # playwright-stealth patches navigator/webdriver properties to suppress automation
    # fingerprints. Optional — scraper still works without it, just gets blocked more.
    try:
        from playwright_stealth import stealth_async
        log.debug("playwright-stealth available; automation fingerprints will be suppressed")
    except Exception:
        stealth_async = None
        log.warning("playwright-stealth not installed; scraper may be detected more often")

    log.info("Launching browser (headless=%s)", HEADLESS)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
            ],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
        page = await context.new_page()
        # Mask automation properties exposed to JS.
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        if stealth_async:
            await stealth_async(page)

        async def visit(url: str) -> str | None:
            if url in seen:
                return None
            seen.add(url)
            if not robots.allowed(url):
                log.info("Skipping robots-disallowed URL: %s", url)
                return None
            html = await _fetch(page, url)
            await _polite_sleep(robots)
            return html

        # Phase 0: Category/brand pages — scan for part URLs directly.
        # This discovers parts that never appear on any model listing page (e.g. generic
        # or cross-brand parts) and seeds part_q before the model crawl even starts.
        cat_seeds = _category_seeds()[:MAX_CATEGORY_PAGES]
        log.info("Phase 0: scanning %d category pages for part URLs", len(cat_seeds))
        cat_found = 0
        for url in cat_seeds:
            html = await visit(url)
            if not html:
                continue
            hrefs = extract_links(html)["part"]
            for href in hrefs:
                part_q.append(urljoin(BASE, href))
            cat_found += len(hrefs)
        log.info("Phase 0 done; %d part URL candidates from category pages", cat_found)

        # Phase 1: Seed + brand index pages — discover model listing and brand index URLs.
        log.info("Phase 1: crawling %d seed URLs for brand/model links", len(brand_q))
        while brand_q:
            url = brand_q.pop(0)
            html = await visit(url)
            if not html:
                continue
            links = extract_links(html)
            for href in links["brand"]:
                brand_q.append(urljoin(BASE, href))
            for href in links["model"]:
                model_q.append(urljoin(BASE, href))
        log.info("Phase 1 done; %d model URLs queued", len(model_q))

        # Phase 2: Model pages — parse and yield each record.
        log.info("Phase 2: crawling up to %d model pages", MAX_MODELS)
        for url in model_q:
            if models_done >= MAX_MODELS:
                log.info("Reached MAX_MODELS=%d; stopping model crawl", MAX_MODELS)
                break
            html = await visit(url)
            if not html:
                continue
            record = parse_model_page(html, url)
            if record:
                models_done += 1
                for href in extract_links(html)["part"]:
                    part_q.append(urljoin(BASE, href))
                yield "model", record
        log.info("Phase 2 done; %d models scraped, %d part URLs queued", models_done, len(part_q))

        # Phase 3: Part pages — dict.fromkeys deduplicates while preserving insertion order.
        log.info("Phase 3: crawling up to %d part pages", MAX_PARTS)
        for url in dict.fromkeys(part_q):
            if parts_done >= MAX_PARTS:
                log.info("Reached MAX_PARTS=%d; stopping part crawl", MAX_PARTS)
                break
            html = await visit(url)
            if not html:
                continue
            record = parse_part_page(html, url)
            if record:
                parts_done += 1
                yield "part", record
        log.info("Phase 3 done; %d parts scraped", parts_done)

        await context.close()
        await browser.close()
