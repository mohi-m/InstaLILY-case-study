"""Fixed set of models to scrape, keyed by appliance category.

Keeping the category here means appliance_type is known up-front and does not depend
on parsing a breadcrumb that anti-bot pages sometimes strip.
"""

DISHWASHERS = [
    "SHP78CM6N",
    "SHP78CM4N!2F01",
    "KDTM604KPS1",
    "KDPM604KBS2",
    "DW90F89T0USRAA",
    "DW90F89T0U12AA",
    "LDPN454HT",
    "LDTH7972S",
    "WDP540HAMZ",
    "WDPS7024RV0",
    "WDT780SAEM1",
]

REFRIGERATORS = [
    "LRFXC2406S",
    "LFCS22520S",
    "LRFXC2416S",
    "RF28R7201SR",
    "RF27T5201SR",
    "RT18DG6500SRAA",
    "WRX735SDHZ00",
    "WRS588FIHZ00",
    "WRT311FZDZ00",
    "GRMC2273CD00",
    "FRSS2623AS0",
    "FFTR1835VS0",
    "KRMF536RPS00",
    "KRFF507HPS03",
    "KBFN536SPS00",
    "ED5FVGXWS01"
]

# Ordered (model_number, appliance_type) pairs for the crawl.
TARGETS: list[tuple[str, str]] = (
    [(m, "Dishwasher") for m in DISHWASHERS]
    + [(m, "Refrigerator") for m in REFRIGERATORS]
)
