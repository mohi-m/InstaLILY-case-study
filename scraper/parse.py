"""HTML parsing for PartSelect pages.

Selectors were validated against captured sample HTML (a model page, its parts
listing, and a part detail page) and are intentionally defensive (multiple fallbacks).
The pages expose schema.org microdata (itemprop=productID/mpn/brand/price/...), which
is the most stable thing to key on. If markup shifts, adjust here — extraction is
isolated to this module.
"""

import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://www.partselect.com"

PS_RE = re.compile(r"PS\d+", re.IGNORECASE)
PS_HREF_RE = re.compile(r"/PS\d+-[^/?#]*\.htm", re.IGNORECASE)
PRICE_RE = re.compile(r"([\d,]+\.\d{2})")
PCT_RE = re.compile(r"(\d{1,3})\s*%")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.replace("\xa0", " ").split()).strip()
    return cleaned or None


def _ps_from_href(href: str) -> str | None:
    m = PS_RE.search(href)
    return m.group(0).upper() if m else None


# --------------------------------------------------------------------------- part


def parse_part_page(html: str, url: str) -> dict[str, Any] | None:
    soup = _soup(html)

    ps_node = soup.select_one("[itemprop='productID']")
    ps_number = _clean(ps_node.get_text()) if ps_node else None
    if not ps_number:
        # itemprop not present — fall back to extracting PS number from the URL.
        m = PS_RE.search(url)
        ps_number = m.group(0).upper() if m else None
    if not ps_number:
        logger.warning("Could not extract PS number from %s — skipping part", url)
        return None
    ps_number = ps_number.upper()

    mfg_node = soup.select_one("[itemprop='mpn']")
    mfg_part_number = _clean(mfg_node.get_text()) if mfg_node else None

    brand_node = soup.select_one("[itemprop='brand'] [itemprop='name']") or soup.select_one(
        "[itemprop='brand']"
    )
    brand = _clean(brand_node.get_text()) if brand_node else None

    name_node = soup.select_one("h1[itemprop='name']") or soup.find("h1")
    name = _clean(name_node.get_text()) if name_node else ps_number

    price = None
    price_node = soup.select_one("[itemprop='price']")
    price_text = (
        price_node.get("content") or price_node.get_text() if price_node else None
    )
    pm = PRICE_RE.search(price_text or "")
    if pm:
        price = float(pm.group(1).replace(",", ""))

    stock_node = soup.select_one("[itemprop='availability']")
    stock_status = None
    if stock_node:
        stock_status = _clean(stock_node.get("content") or stock_node.get_text())

    install_difficulty, install_time = _parse_repair_rating(soup)

    image_url = _parse_part_image(soup)

    desc_node = soup.select_one("[itemprop='description']")
    description = _clean(desc_node.get_text(" ")) if desc_node else None

    install_instructions = _parse_install_instructions(soup)

    symptoms = _parse_part_fix_symptoms(soup)

    logger.debug("Parsed part %s: name=%r price=%s symptoms=%d",
                 ps_number, name, price, len(symptoms))

    return {
        "ps_number": ps_number,
        "mfg_part_number": mfg_part_number,
        "name": name,
        "brand": brand,
        "price": price,
        "stock_status": stock_status,
        "install_difficulty": install_difficulty,
        "install_time": install_time,
        "image_url": image_url,
        "description": description,
        "install_instructions": install_instructions,
        "symptoms": symptoms,
        "url": url.split("?")[0],
    }


def _parse_repair_rating(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Within .pd__repair-rating__container the two bold <p>s are difficulty + time,
    distinguished by the adjacent svg <use href> ending in #difficulty / #duration."""
    container = soup.select_one(".pd__repair-rating__container")
    if not container:
        return None, None
    difficulty = time = None
    for div in container.find_all("div"):
        use = div.find("use")
        p = div.find("p")
        if not use or not p:
            continue
        href = use.get("href") or use.get("xlink:href") or ""
        text = _clean(p.get_text())
        if "difficulty" in href.lower():
            difficulty = text
        elif "duration" in href.lower():
            time = text
    return difficulty, time


def _parse_part_image(soup: BeautifulSoup) -> str | None:
    for img in soup.select("img[itemprop='image']"):
        src = img.get("src") or img.get("data-src") or ""
        alt = (img.get("alt") or "").lower()
        if src.startswith("http") and "diagram" not in alt and "location" not in alt:
            return src
    # Fallback: any product image with a real src.
    for img in soup.select("img[itemprop='image']"):
        src = img.get("src") or img.get("data-src") or ""
        if src.startswith("http"):
            return src
    return None


def _parse_install_instructions(soup: BeautifulSoup, limit: int = 3) -> str | None:
    parts: list[str] = []
    for story in soup.select(".repair-story")[:limit]:
        instr = story.select_one(".repair-story__instruction .js-searchKeys")
        text = _clean(instr.get_text(" ")) if instr else None
        if text:
            parts.append(text)
    return "\n\n".join(parts) if parts else None


def _parse_part_fix_symptoms(soup: BeautifulSoup) -> list[str]:
    # The "Troubleshooting" title div and its content are siblings, so search globally
    # for the labelled block rather than scoping to #Troubleshooting.
    symptoms: list[str] = []
    header = soup.find(string=re.compile(r"fixes the following symptoms", re.I))
    if header and header.find_parent():
        ul = header.find_parent().find_next("ul")
        if ul:
            for li in ul.find_all("li"):
                s = _clean(li.get_text())
                if s:
                    symptoms.append(s)
    return list(dict.fromkeys(symptoms))


# --------------------------------------------------------------------------- model


def parse_model_page(html: str, url: str) -> dict[str, Any]:
    soup = _soup(html)

    brand = None
    appliance_type = None
    qa_input = soup.select_one("#qandawithinmodel")
    if qa_input:
        brand = _clean(qa_input.get("data-track-search-pagebrand"))
        appliance_type = _clean(qa_input.get("data-track-search-pagemodeltype"))

    name_node = soup.find("h1")
    name = _clean(name_node.get_text()) if name_node else None

    qa = _parse_model_qa(soup)
    symptom_links = _parse_symptom_links(soup, url)

    logger.debug("Parsed model page %s: brand=%r qa=%d symptom_links=%d",
                 url, brand, len(qa), len(symptom_links))

    return {
        "brand": brand,
        "appliance_type": appliance_type,
        "name": name,
        "qa": qa,
        "symptom_links": symptom_links,
    }


def _parse_model_qa(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in soup.select(".qna__question.js-qnaResponse, .qna__question"):
        keys = block.select(".js-searchKeys")
        question = _clean(keys[0].get_text(" ")) if keys else None
        ans_node = block.select_one(".qna__ps-answer__msg .js-searchKeys")
        answer = _clean(ans_node.get_text(" ")) if ans_node else None
        parts: list[dict[str, str]] = []
        seen: set[str] = set()
        for a in block.select(".qna__question__related a[href]"):
            ps = _ps_from_href(a["href"])
            if ps and ps not in seen:
                seen.add(ps)
                parts.append({"ps": ps, "url": urljoin(BASE, a["href"].split("?")[0])})
        if question:
            out.append({"question": question, "answer": answer, "parts": parts})
    return out


def _parse_symptom_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a.symptoms[href*='/Symptoms/']"):
        href = a.get("href")
        descr = a.select_one(".symptoms__descr")
        name = _clean(descr.get_text()) if descr else _clean(a.get_text())
        if not href or not name or href in seen:
            continue
        seen.add(href)
        out.append({"name": name, "url": urljoin(base_url, href)})
    return out


# --------------------------------------------------------------------------- parts listing


def parse_parts_listing(html: str) -> dict[str, Any]:
    soup = _soup(html)
    ps_numbers: list[str] = []
    part_urls: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not PS_HREF_RE.search(href):
            continue
        ps = _ps_from_href(href)
        if not ps or ps in part_urls:
            continue
        clean_url = urljoin(BASE, href.split("?")[0].split("#")[0])
        part_urls[ps] = clean_url
        ps_numbers.append(ps)

    next_url = None
    next_a = soup.select_one("ul.pagination.js-pagination li.next a[href]")
    if next_a and "disabled" not in (next_a.find_parent("li").get("class") or []):
        next_url = urljoin(BASE, next_a["href"])

    logger.debug("Parts listing: found %d part(s), next_url=%s", len(ps_numbers), next_url)

    return {
        "ps_numbers": ps_numbers,
        "part_urls": [part_urls[ps] for ps in ps_numbers],
        "next_url": next_url,
    }


# --------------------------------------------------------------------------- symptom page


def parse_symptom_page(html: str, top_n: int = 3) -> list[dict[str, Any]]:
    """Return [{ps_number, effectiveness, url}] for parts that fix this symptom, top-N by %.

    Each part is a `div.symptoms` block with `.symptoms__percent` ("Fixes Symptom 26%
    of time") and a PS link. Falls back to a generic anchor+nearby-percentage scan if
    the expected markup is absent.
    """
    soup = _soup(html)
    found: dict[str, dict[str, Any]] = {}

    for block in soup.select("div.symptoms"):
        pct_node = block.select_one(".symptoms__percent")
        if not pct_node:
            continue
        m = PCT_RE.search(pct_node.get_text(" "))
        if not m:
            continue
        a = next(
            (x for x in block.find_all("a", href=True) if PS_HREF_RE.search(x["href"])),
            None,
        )
        if not a:
            continue
        ps = _ps_from_href(a["href"])
        if not ps:
            continue
        pct = float(m.group(1))
        if ps not in found or pct > found[ps]["effectiveness"]:
            found[ps] = {
                "ps_number": ps,
                "effectiveness": pct,
                "url": urljoin(BASE, a["href"].split("?")[0].split("#")[0]),
            }

    if not found:
        # Primary selector found nothing — page markup may have changed; try raw anchor scan.
        logger.debug("Primary symptom selector found no results — falling back to anchor scan")
        for a in soup.find_all("a", href=True):
            if not PS_HREF_RE.search(a["href"]):
                continue
            ps = _ps_from_href(a["href"])
            if not ps:
                continue
            pct = _nearby_percentage(a) or 0.0
            url = urljoin(BASE, a["href"].split("?")[0].split("#")[0])
            if ps not in found or pct > found[ps]["effectiveness"]:
                found[ps] = {"ps_number": ps, "effectiveness": pct, "url": url}

    ranked = sorted(found.values(), key=lambda d: d["effectiveness"], reverse=True)[:top_n]
    for d in ranked:
        d["effectiveness"] = d["effectiveness"] or None
    logger.debug("Symptom page: %d part(s) found (top %d returned)", len(found), len(ranked))
    return ranked


def _nearby_percentage(node) -> float | None:
    """Search the anchor's ancestors for a '<n>%' token."""
    cur = node
    for _ in range(4):
        if cur is None:
            break
        m = PCT_RE.search(cur.get_text(" ") if hasattr(cur, "get_text") else "")
        if m:
            return float(m.group(1))
        cur = cur.parent
    return None
