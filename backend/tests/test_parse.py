"""Offline tests for the targeted scraper's HTML parsers (scraper/parse.py)."""

from parse import parse_parts_listing, parse_part_page, parse_symptom_page

PARTS_LISTING = """
<div class="parts">
  <a href="/PS100-foo-part.htm">Foo</a>
  <a href="/PS100-foo-part.htm#CustomerReview">Foo review</a>
  <a href="/PS200-bar-part.htm?SourceCode=21">Bar</a>
  <a href="/About.htm">ignore</a>
</div>
<ul class="pagination js-pagination">
  <li class="prev disabled"><a role="button">Prev</a></li>
  <li class="active"><a href="/Models/M/Parts/">1</a></li>
  <li class="next"><a href="/Models/M/Parts/?start=2">Next</a></li>
</ul>
"""

# Fallback path: bare anchors with a nearby percentage (no .symptoms markup).
SYMPTOM_PAGE = """
<div><a href="/PS1-a.htm">A</a><span>90% of customers</span></div>
<div><a href="/PS2-b.htm">B</a><span>75% of customers</span></div>
<div><a href="/PS3-c.htm">C</a><span>50% of customers</span></div>
<div><a href="/PS4-d.htm">D</a><span>30% of customers</span></div>
"""

# Primary path: real PartSelect markup (div.symptoms + .symptoms__percent).
SYMPTOM_PAGE_REAL = """
<div class="symptoms align-items-center ">
  <div class="symptoms__percent"><div>Fixes Symptom <span>26%</span> of time</div></div>
  <a href="/PS100-door-seal.htm?SourceCode=22">Door Seal</a>
</div>
<div class="symptoms align-items-center ">
  <div class="symptoms__percent"><div>Fixes Symptom <span>9%</span> of time</div></div>
  <a href="/PS200-spray-arm.htm">Spray Arm</a>
</div>
<div class="symptoms align-items-center d-none">
  <div class="symptoms__percent"><div>Fixes Symptom <span>4%</span> of time</div></div>
  <a href="/PS300-grommet.htm">Grommet</a>
</div>
<div class="symptoms align-items-center d-none">
  <div class="symptoms__percent"><div>Fixes Symptom <span>1%</span> of time</div></div>
  <a href="/PS400-valve.htm">Valve</a>
</div>
"""

PART_PAGE = """
<h1 itemprop="name">Lower Dishrack Wheel W10195416</h1>
<span itemprop="productID">PS3406971</span>
<span itemprop="mpn">W10195416</span>
<span itemprop="brand"><span itemprop="name">Whirlpool</span></span>
<span itemprop="price" content="33.6900">$33.69</span>
<span itemprop="availability" content="InStock">In Stock</span>
<div class="pd__repair-rating__container">
  <div><svg><use href="/images/story-sprite.svg#difficulty"></use></svg><p class="bold">Very Easy</p></div>
  <div><svg><use href="/images/story-sprite.svg#duration"></use></svg><p class="bold">15 - 30 mins</p></div>
</div>
<img itemprop="image" src="https://img.example.com/3406971.jpg" alt="Lower Dishrack Wheel">
<div itemprop="description">A plastic kit that allows the rack to slide.</div>
<div class="bold">This part fixes the following symptoms:</div>
<ul class="list-disc"><li>Leaking</li><li>Noisy</li></ul>
"""


def test_parts_listing_dedupes_and_finds_next():
    parsed = parse_parts_listing(PARTS_LISTING)
    assert parsed["ps_numbers"] == ["PS100", "PS200"]
    assert parsed["next_url"].endswith("/Models/M/Parts/?start=2")
    assert all("About" not in u for u in parsed["part_urls"])


def test_symptom_page_returns_top_3_by_effectiveness():
    rows = parse_symptom_page(SYMPTOM_PAGE, top_n=3)
    assert [r["ps_number"] for r in rows] == ["PS1", "PS2", "PS3"]
    assert [r["effectiveness"] for r in rows] == [90.0, 75.0, 50.0]


def test_symptom_page_real_markup_top_3():
    rows = parse_symptom_page(SYMPTOM_PAGE_REAL, top_n=3)
    assert [r["ps_number"] for r in rows] == ["PS100", "PS200", "PS300"]
    assert [r["effectiveness"] for r in rows] == [26.0, 9.0, 4.0]
    assert rows[0]["url"].endswith("/PS100-door-seal.htm")


def test_part_page_extracts_microdata():
    rec = parse_part_page(PART_PAGE, "https://www.partselect.com/PS3406971-x.htm")
    assert rec["ps_number"] == "PS3406971"
    assert rec["mfg_part_number"] == "W10195416"
    assert rec["brand"] == "Whirlpool"
    assert rec["price"] == 33.69
    assert rec["install_difficulty"] == "Very Easy"
    assert rec["install_time"] == "15 - 30 mins"
    assert rec["image_url"] == "https://img.example.com/3406971.jpg"
    assert rec["symptoms"] == ["Leaking", "Noisy"]
