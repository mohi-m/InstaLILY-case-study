from bs4 import BeautifulSoup

from parse import (
    appliance_from_breadcrumb,
    BRAND_INDEX_RE,
    MODEL_PAGE_RE,
    PART_PAGE_RE,
    extract_links,
)

FRIDGE = """<nav class="breadcrumb"><a>Home</a><a>Refrigerator</a><a>Whirlpool</a></nav>"""
DISH = """<ol class="breadcrumb-list"><li>Home</li><li>Dishwasher</li></ol>"""
OUT_OF_SCOPE = """<nav class="breadcrumb"><a>Home</a><a>Microwave</a></nav>"""


def test_breadcrumb_detects_refrigerator():
    assert appliance_from_breadcrumb(BeautifulSoup(FRIDGE, "lxml")) == "Refrigerator"


def test_breadcrumb_detects_dishwasher():
    assert appliance_from_breadcrumb(BeautifulSoup(DISH, "lxml")) == "Dishwasher"


def test_breadcrumb_drops_out_of_scope():
    assert appliance_from_breadcrumb(BeautifulSoup(OUT_OF_SCOPE, "lxml")) is None


def test_frontier_link_patterns():
    assert BRAND_INDEX_RE.search("/Whirlpool-Refrigerator-Models.htm")
    assert BRAND_INDEX_RE.search("/Bosch-Dishwasher-Models.htm")
    assert not BRAND_INDEX_RE.search("/Whirlpool-Microwave-Models.htm")
    assert MODEL_PAGE_RE.search("/Models/WDT780SAEM1/")
    assert PART_PAGE_RE.search("/PS11752778-Whirlpool-Door-Shelf.htm")


def test_extract_links_buckets():
    html = """
      <a href="/Whirlpool-Refrigerator-Models.htm">brand</a>
      <a href="/Models/WDT780SAEM1/">model</a>
      <a href="/PS11752778-part.htm">part</a>
      <a href="/About.htm">ignore</a>
    """
    links = extract_links(html)
    assert links["brand"] and links["model"] and links["part"]
    assert all("About" not in v for bucket in links.values() for v in bucket)
