"""HTML parsing + breadcrumb scope validation for PartSelect pages.

Selectors are best-effort against PartSelect's current markup and are intentionally
defensive (multiple fallbacks). If the site's markup shifts, adjust the selectors
here — extraction is isolated to this module.
"""

import re
from typing import Any

from bs4 import BeautifulSoup

PS_NUMBER_RE = re.compile(r"PS\d+", re.IGNORECASE)
PRICE_RE = re.compile(r"\$?\s*([\d,]+\.\d{2})")

# Link patterns for the scope-locked frontier.
BRAND_INDEX_RE = re.compile(r"/[^/]*-(Refrigerator|Dishwasher)-Models\.htm$", re.IGNORECASE)
MODEL_PAGE_RE = re.compile(r"/Models/[^/]+/?$", re.IGNORECASE)
PART_PAGE_RE = re.compile(r"/PS\d+-[^/]*\.htm$", re.IGNORECASE)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def appliance_from_breadcrumb(soup: BeautifulSoup) -> str | None:
    """Return 'Refrigerator' or 'Dishwasher' if present in the breadcrumb, else None.

    This is the hard scope gate: a page whose breadcrumb mentions neither is dropped.
    """
    crumb = soup.select_one(
        "[class*='breadcrumb'], nav[aria-label*='readcrumb'], .bread-crumb, #breadcrumb"
    )
    text = (crumb.get_text(" ", strip=True) if crumb else soup.get_text(" ", strip=True))
    lowered = text.lower()
    # Prefer the breadcrumb; fall back to page text only for the type word.
    if "refrigerator" in lowered:
        return "Refrigerator"
    if "dishwasher" in lowered:
        return "Dishwasher"
    return None


def extract_links(html: str) -> dict[str, list[str]]:
    soup = _soup(html)
    brand, model, part = [], [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].split("#")[0]
        if BRAND_INDEX_RE.search(href):
            brand.append(href)
        elif MODEL_PAGE_RE.search(href):
            model.append(href)
        elif PART_PAGE_RE.search(href):
            part.append(href)
    return {"brand": brand, "model": model, "part": part}


def _text_after_label(soup: BeautifulSoup, label: str) -> str | None:
    node = soup.find(string=re.compile(label, re.IGNORECASE))
    if node and node.parent:
        sib = node.parent.find_next(string=True)
        if sib:
            return sib.strip()
    return None


def parse_part_page(html: str, url: str) -> dict[str, Any] | None:
    soup = _soup(html)
    appliance = appliance_from_breadcrumb(soup)
    if appliance is None:
        return None  # out of scope per breadcrumb rule

    ps_match = PS_NUMBER_RE.search(url) or PS_NUMBER_RE.search(soup.get_text(" "))
    if not ps_match:
        return None
    ps_number = ps_match.group(0).upper()

    mfg = _text_after_label(soup, r"Manufacturer Part Number")
    name_node = soup.find("h1")
    name = name_node.get_text(strip=True) if name_node else ps_number

    price = None
    price_node = soup.select_one("[itemprop='price'], .price, .pd__price")
    price_text = price_node.get_text(" ", strip=True) if price_node else soup.get_text(" ")
    pm = PRICE_RE.search(price_text or "")
    if pm:
        price = float(pm.group(1).replace(",", ""))

    desc_node = soup.select_one(
        ".pd__description, [class*='product-description'], #ProductDescription"
    )
    description = desc_node.get_text(" ", strip=True) if desc_node else None

    install_node = soup.select_one(
        "[class*='installation'], #InstallationInstructions, .pd__install"
    )
    install = install_node.get_text("\n", strip=True) if install_node else None

    symptoms: list[str] = []
    sym_header = soup.find(string=re.compile(r"fixes the following symptoms", re.I))
    if sym_header and sym_header.find_parent():
        container = sym_header.find_parent()
        for li in container.find_all_next("li", limit=20):
            symptoms.append(li.get_text(" ", strip=True))

    qa: list[dict[str, str]] = []
    for q in soup.select("[class*='qna'] [class*='question'], .qa-question"):
        question = q.get_text(" ", strip=True)
        ans_node = q.find_next(class_=re.compile("answer", re.I))
        answer = ans_node.get_text(" ", strip=True) if ans_node else ""
        if question:
            qa.append({"question": question, "answer": answer})

    stock = None
    stock_node = soup.select_one("[class*='stock'], [itemprop='availability']")
    if stock_node:
        stock = stock_node.get_text(" ", strip=True)

    return {
        "ps_number": ps_number,
        "mfg_part_number": mfg,
        "name": name,
        "appliance_type": appliance,
        "price": price,
        "stock_status": stock,
        "description": description,
        "install_instructions": install,
        "symptoms": symptoms,
        "qa": qa,
        "url": url,
    }


def parse_model_page(html: str, url: str) -> dict[str, Any] | None:
    soup = _soup(html)
    appliance = appliance_from_breadcrumb(soup)
    if appliance is None:
        return None

    m = re.search(r"/Models/([^/]+)/?", url)
    model_number = m.group(1).upper() if m else None
    if not model_number:
        return None

    name_node = soup.find("h1")
    name = name_node.get_text(strip=True) if name_node else model_number

    compatible_ps: list[str] = []
    for a in soup.find_all("a", href=True):
        pm = PS_NUMBER_RE.search(a["href"])
        if pm and PART_PAGE_RE.search(a["href"].split("?")[0]):
            compatible_ps.append(pm.group(0).upper())

    common_symptoms: list[str] = []
    sym_header = soup.find(string=re.compile(r"Common (Symptoms|Repairs)", re.I))
    if sym_header and sym_header.find_parent():
        for li in sym_header.find_parent().find_all_next("li", limit=20):
            common_symptoms.append(li.get_text(" ", strip=True))

    diagrams: list[dict[str, str]] = []
    for img in soup.select(
        "img[src*='Schematic'], img[src*='diagram'], a[href*='Schematic'], a[href*='diagram']"
    ):
        src = img.get("src") or img.get("href")
        if src:
            diagrams.append(
                {"name": img.get("alt") or "Diagram", "image_url": src, "section": None}
            )

    return {
        "model_number": model_number,
        "appliance_type": appliance,
        "name": name,
        "compatible_ps": list(dict.fromkeys(compatible_ps)),
        "common_symptoms": common_symptoms,
        "diagrams": diagrams,
        "url": url,
    }
