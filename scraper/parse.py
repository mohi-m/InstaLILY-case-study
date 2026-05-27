"""HTML parsing + breadcrumb scope validation for PartSelect pages.

Selectors are best-effort against PartSelect's current markup and are intentionally
defensive (multiple fallbacks). If the site's markup shifts, adjust the selectors
here — extraction is isolated to this module.
"""

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

PS_NUMBER_RE = re.compile(r"PS\d+", re.IGNORECASE)
PRICE_RE = re.compile(r"\$?\s*([\d,]+\.\d{2})")

# Link patterns for the scope-locked frontier.
BRAND_INDEX_RE = re.compile(r"/[^/]*-(Refrigerator|Dishwasher)-Models\.htm$", re.IGNORECASE)
MODEL_PAGE_RE = re.compile(r"/Models/[^/]+/?$", re.IGNORECASE)
PART_PAGE_RE = re.compile(r"/PS\d+-[^/]*\.htm$", re.IGNORECASE)

_KNOWN_BRANDS = frozenset({
    "Whirlpool", "GE", "Samsung", "LG", "Frigidaire", "Kenmore", "KitchenAid",
    "Maytag", "Bosch", "Amana", "Electrolux", "Hotpoint", "Jenn-Air", "Thermador",
    "Haier", "Crosley", "Dacor", "Viking", "Miele",
})


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _extract_brand(soup: BeautifulSoup) -> str | None:
    """Try several extraction strategies to identify the appliance brand."""
    # Schema.org itemprop (most reliable when present)
    node = soup.select_one("[itemprop='brand']")
    if node:
        name_node = node.select_one("[itemprop='name']") or node
        text = name_node.get_text(strip=True)
        if text:
            return text
    # Explicit "Brand:" label anywhere on the page
    label = soup.find(string=re.compile(r"^\s*Brand\s*:?\s*$", re.I))
    if label and label.parent:
        sib = label.parent.find_next_sibling()
        if sib:
            text = sib.get_text(strip=True)
            if text:
                return text
    # Match known brands against breadcrumb text (fallback)
    crumb = soup.select_one(
        "[class*='breadcrumb'], nav[aria-label*='readcrumb'], .bread-crumb, #breadcrumb"
    )
    text = crumb.get_text(" ", strip=True) if crumb else ""
    lower = text.lower()
    for brand in _KNOWN_BRANDS:
        if brand.lower() in lower:
            return brand
    return None


def _extract_install_steps(install_node) -> str | None:
    """Return install instructions as a clean newline-delimited string.

    Prefers explicit list items; falls back to raw text. One step per line
    makes downstream splitting reliable.
    """
    if not install_node:
        return None
    items = install_node.select("ol li, ul li")
    if items:
        steps = []
        for i, li in enumerate(items, 1):
            text = li.get_text(" ", strip=True)
            if text and len(text) < 600:
                # Normalise: ensure each line already starts with its own number or use ours
                if not re.match(r"^\d+\.", text):
                    text = f"{i}. {text}"
                steps.append(text)
        if steps:
            return "\n".join(steps)
    raw = install_node.get_text("\n", strip=True)
    return raw if raw else None


def appliance_from_breadcrumb(soup: BeautifulSoup) -> str | None:
    """Return 'Refrigerator' or 'Dishwasher' if present in the breadcrumb, else None.

    This is the hard scope gate: a page whose breadcrumb mentions neither is dropped.
    """
    crumb = soup.select_one(
        "[class*='breadcrumb'], nav[aria-label*='readcrumb'], .bread-crumb, #breadcrumb"
    )
    # Fall back to full page text only if no dedicated breadcrumb element is found.
    text = (crumb.get_text(" ", strip=True) if crumb else soup.get_text(" ", strip=True))
    lowered = text.lower()
    if "refrigerator" in lowered:
        return "Refrigerator"
    if "dishwasher" in lowered:
        return "Dishwasher"
    return None


def extract_links(html: str) -> dict[str, list[str]]:
    """Return categorised href lists from a page: brand index, model, and part links."""
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
    log.debug(
        "extract_links: %d brand, %d model, %d part hrefs found",
        len(brand), len(model), len(part),
    )
    return {"brand": brand, "model": model, "part": part}


def _text_after_label(soup: BeautifulSoup, label: str) -> str | None:
    node = soup.find(string=re.compile(label, re.IGNORECASE))
    if node and node.parent:
        sib = node.parent.find_next(string=True)
        if sib:
            return sib.strip()
    return None


def _first_text(soup: BeautifulSoup, *selectors: str) -> str | None:
    """Return stripped text of the first element matched by any selector."""
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            return node.get_text(" ", strip=True) or None
    return None


def parse_part_page(html: str, url: str) -> dict[str, Any] | None:
    soup = _soup(html)
    appliance = appliance_from_breadcrumb(soup)
    if appliance is None:
        log.debug("parse_part_page: scope drop (no Refrigerator/Dishwasher breadcrumb) for %s", url)
        return None  # out of scope per breadcrumb rule

    ps_match = PS_NUMBER_RE.search(url) or PS_NUMBER_RE.search(soup.get_text(" "))
    if not ps_match:
        log.debug("parse_part_page: no PS number found for %s", url)
        return None
    ps_number = ps_match.group(0).upper()

    brand = _extract_brand(soup)
    mfg = _text_after_label(soup, r"Manufacturer Part Number")

    name_node = soup.find("h1")
    name = name_node.get_text(strip=True) if name_node else ps_number

    # Price — try schema.org itemprop first (most stable), then common class names.
    price = None
    price_node = soup.select_one(
        "[itemprop='price'], [data-price], .js-partPrice, "
        ".pd__price, .price, .pricing__price, [class*='partPrice'], [class*='part-price']"
    )
    # If no dedicated node, scan visible text for a dollar amount.
    price_text = price_node.get_text(" ", strip=True) if price_node else ""
    if not price_text:
        price_text = soup.get_text(" ")
    pm = PRICE_RE.search(price_text or "")
    if pm:
        price = float(pm.group(1).replace(",", ""))

    # Description — PartSelect uses `pd__description` but class names drift; try many.
    description = _first_text(
        soup,
        ".pd__description",
        "#PartDescription",
        "#ProductDescription",
        "[class*='partDescription']",
        "[class*='product-description']",
        "[class*='productDescription']",
        "[itemprop='description']",
    )

    # Install instructions — often in a tab/accordion keyed on "installation".
    install_node = soup.select_one(
        "#Installation, #InstallationInstructions, "
        "[class*='installation'], [data-tab*='nstall'], .pd__install, "
        "[class*='how-to-install'], [id*='nstall']"
    )
    install = _extract_install_steps(install_node)

    # Symptoms section — look for the section header then collect list items.
    symptoms: list[str] = []
    for pattern in (r"fixes the following symptoms", r"This part fixes", r"Symptoms"):
        sym_header = soup.find(string=re.compile(pattern, re.I))
        if sym_header and sym_header.find_parent():
            container = sym_header.find_parent()
            items = container.find_all_next("li", limit=30)
            if not items:
                # Sometimes wrapped in a sibling div rather than a list.
                sibling = container.find_next_sibling()
                if sibling:
                    items = sibling.find_all("li", limit=30)
            for li in items:
                text = li.get_text(" ", strip=True)
                if text and len(text) < 200:
                    symptoms.append(text)
            if symptoms:
                break

    # Q&A — PartSelect renders these in various container class patterns.
    qa: list[dict[str, str]] = []
    for q in soup.select(
        "[class*='qna'] [class*='question'], .qa-question, "
        "[class*='question'], [class*='Question']"
    ):
        question = q.get_text(" ", strip=True)
        if not question or len(question) > 500:
            continue
        ans_node = q.find_next(class_=re.compile(r"answer|Answer", re.I))
        answer = ans_node.get_text(" ", strip=True) if ans_node else ""
        qa.append({"question": question, "answer": answer})

    # Stock status.
    stock = _first_text(
        soup,
        "[itemprop='availability']",
        "[class*='stock']",
        "[class*='availability']",
        "[class*='instock']",
        "[class*='out-of-stock']",
    )

    log.debug(
        "Parsed part %s (%s, %s): price=%s, symptoms=%d, qa=%d",
        ps_number, appliance, brand, price, len(symptoms), len(qa),
    )
    return {
        "ps_number": ps_number,
        "mfg_part_number": mfg,
        "name": name,
        "brand": brand,
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
        log.debug("parse_model_page: scope drop (no Refrigerator/Dishwasher breadcrumb) for %s", url)
        return None

    m = re.search(r"/Models/([^/]+)/?", url)
    model_number = m.group(1).upper() if m else None
    if not model_number:
        log.debug("parse_model_page: could not extract model number from %s", url)
        return None

    brand = _extract_brand(soup)
    name_node = soup.find("h1")
    name = name_node.get_text(strip=True) if name_node else model_number

    compatible_ps: list[str] = []
    for a in soup.find_all("a", href=True):
        pm = PS_NUMBER_RE.search(a["href"])
        if pm and PART_PAGE_RE.search(a["href"].split("?")[0]):
            compatible_ps.append(pm.group(0).upper())

    common_symptoms: list[str] = []
    for pattern in (r"Common (Symptoms|Repairs|Problems)", r"Most Common Repairs"):
        sym_header = soup.find(string=re.compile(pattern, re.I))
        if sym_header and sym_header.find_parent():
            container = sym_header.find_parent()
            for li in container.find_all_next("li", limit=20):
                text = li.get_text(" ", strip=True)
                if text and len(text) < 200:
                    common_symptoms.append(text)
            if common_symptoms:
                break

    diagrams: list[dict[str, str]] = []
    for img in soup.select(
        "img[src*='Schematic'], img[src*='diagram'], a[href*='Schematic'], a[href*='diagram']"
    ):
        src = img.get("src") or img.get("href")
        if src:
            diagrams.append(
                {"name": img.get("alt") or "Diagram", "image_url": src, "section": None}
            )

    log.debug(
        "Parsed model %s (%s, %s): %d compat parts, %d symptoms, %d diagrams",
        model_number, appliance, brand, len(compatible_ps), len(common_symptoms), len(diagrams),
    )
    return {
        "model_number": model_number,
        "brand": brand,
        "appliance_type": appliance,
        "name": name,
        "compatible_ps": list(dict.fromkeys(compatible_ps)),
        "common_symptoms": common_symptoms,
        "diagrams": diagrams,
        "url": url,
    }
