"""Generator-side judgment calls, not sourced facts.

MDR is explicitly non-statutory (PRD §5.4: "belongs in a merchant
rate-card fixture, never in the tax module"), so MDR-by-method has no
citation to carry. Commission-by-category and the seller roster size are
pure synthetic-data design, chosen for a reasonable-looking demo dataset.
GOODS_GST_BPS is a separate constant from rates.GST_ON_FEES_BPS even
though both are currently 18% -- one splits order_line's taxable/GST
amounts, the other taxes MDR; conflating them would blur a generator
choice with a sourced PRD fact.
"""

GOODS_GST_BPS = 1800

MDR_BPS_BY_METHOD = {
    "upi": 0,
    "card": 180,
    "netbanking": 100,
    "wallet": 150,
}

CATEGORIES = ["electronics", "fashion", "grocery", "home", "beauty"]

COMMISSION_BPS_BY_CATEGORY = {
    "electronics": 1500,
    "fashion": 1800,
    "grocery": 800,
    "home": 1200,
    "beauty": 1600,
}

SELLER_COUNT = 15

# The canonical world only ever holds seller_id. intent.csv needs a human
# name -- a real platform DB export wouldn't show sel_00001 to itself --
# so this exists purely for that source's realism. Indexed by seller
# number (1-based), same as seller_id's own numbering.
#
# sel_00001 and sel_00011 share a name deliberately -- two different
# electronics sellers, both "Sharma Electronics". Real seller directories
# collide on display name; sellers.csv (P1's seller master file) is the
# thing that makes that collision representable and load-bearing rather
# than decorative, and ingest (intent.py) has to handle it honestly
# rather than assume name uniquely identifies a seller.
SELLER_NAMES = [
    "Sharma Electronics",
    "Bright Fashion House",
    "Fresh Mart Grocers",
    "Comfort Home Furnishings",
    "Glow Beauty Studio",
    "Metro Electronics Hub",
    "Trendy Threads Fashion",
    "Green Valley Grocers",
    "Nest Home Essentials",
    "Radiance Beauty Co",
    "Sharma Electronics",
    "Urban Style Fashion",
    "Daily Needs Grocers",
    "Cozy Corner Home",
    "Pure Glow Beauty",
]

