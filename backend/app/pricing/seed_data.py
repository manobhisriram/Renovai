"""SAMPLE catalog data. All prices are illustrative demo values (INR), NOT real market prices.

Replace via the admin API (PUT /api/v1/materials/{sku}) or by editing this file before seeding.
"""

# group: (unit, trade, labour hrs/unit, (lead budget, standard, premium), (price b, s, p), (name b, s, p))
MATERIAL_GROUPS: dict[str, tuple] = {
    "kitchen_cabinets": ("sqft", "carpenter", 0.35, (21, 28, 42), (900, 1400, 2400),
        ("Laminate BWR modular unit", "Acrylic-finish BWP modular unit", "PU-finish modular unit, soft-close hardware")),
    "countertop": ("sqft", "stone_mason", 0.25, (7, 10, 21), (250, 450, 900),
        ("Granite countertop", "Engineered quartz-look slab", "Premium quartz slab")),
    "backsplash": ("sqft", "tiler", 0.30, (5, 7, 14), (70, 140, 320),
        ("Ceramic wall tile", "Glazed vitrified tile", "Glass / mosaic tile")),
    "floor_tiles": ("sqft", "tiler", 0.18, (5, 7, 14), (60, 110, 280),
        ("Ceramic floor tile 600x600", "Vitrified GVT 800x800", "Large-format porcelain slab")),
    "wood_flooring": ("sqft", "carpenter", 0.15, (7, 10, 21), (120, 220, 520),
        ("Laminate flooring", "Engineered wood flooring", "Solid wood flooring")),
    "wall_paint": ("sqft", "painter", 0.025, (2, 2, 4), (18, 28, 55),
        ("Emulsion, 2 coats", "Premium emulsion with putty", "Designer / texture finish")),
    "wall_tiles": ("sqft", "tiler", 0.28, (5, 7, 14), (55, 105, 260),
        ("Ceramic wall tile", "Glazed vitrified wall tile", "Large-format porcelain wall tile")),
    "wall_panels": ("sqft", "carpenter", 0.22, (7, 10, 21), (150, 320, 750),
        ("WPC / PVC panel", "Veneer panel", "Fluted solid-wood / acoustic panel")),
    "false_ceiling": ("sqft", "carpenter", 0.12, (5, 7, 10), (85, 130, 240),
        ("Plain gypsum ceiling", "Gypsum ceiling with cove lighting", "Designer multi-layer ceiling")),
    "wardrobe": ("sqft", "carpenter", 0.40, (21, 28, 42), (850, 1350, 2300),
        ("Laminate sliding wardrobe", "Acrylic hinged wardrobe", "PU-finish wardrobe with internals")),
    "tv_unit": ("nos", "carpenter", 12.0, (14, 21, 35), (18000, 32000, 65000),
        ("Laminate TV unit", "Veneer TV unit with storage", "Designer TV wall with panelling")),
    "vanity": ("nos", "carpenter", 4.0, (7, 14, 28), (6500, 14000, 38000),
        ("PVC vanity unit", "Laminate vanity with basin", "Solid-surface vanity")),
    "sanitaryware": ("nos", "plumber", 3.0, (5, 7, 14), (7500, 16000, 42000),
        ("Standard WC + basin set", "Wall-hung WC + basin set", "Designer wall-hung suite")),
    "cp_fittings": ("nos", "plumber", 2.5, (5, 7, 14), (4500, 9500, 26000),
        ("Standard CP fittings set", "Premium CP fittings set", "Designer shower + CP set")),
    "waterproofing": ("sqft", "civil", 0.08, (2, 3, 5), (35, 60, 110),
        ("Cementitious coating", "Polymer-modified coating", "Membrane system, 10-yr warranty")),
    "plumbing_works": ("nos", "plumber", 2.0, (3, 5, 7), (1800, 2600, 4200),
        ("CPVC points, standard", "CPVC points, premium pipe", "Concealed premium plumbing points")),
    "plumbing_fixtures": ("nos", "plumber", 3.0, (5, 7, 14), (6500, 14000, 34000),
        ("Stainless sink + tap", "Quartz sink + pull-out tap", "Designer sink + filtered-water tap")),
    "light_fixtures": ("nos", "electrician", 0.6, (3, 7, 14), (450, 1200, 4200),
        ("LED panel / downlight", "Branded LED fixture", "Designer pendant / profile lighting")),
    "electrical_points": ("nos", "electrician", 1.2, (3, 3, 5), (650, 900, 1400),
        ("Standard modular point", "Branded modular point", "Premium modular point")),
    "demolition": ("sqft", "civil", 0.15, (1, 1, 1), (8, 8, 8),
        ("Demolition + debris disposal", "Demolition + debris disposal", "Demolition + debris disposal")),
    "skirting": ("rft", "carpenter", 0.08, (3, 5, 10), (35, 70, 160),
        ("PVC skirting", "MDF skirting", "Solid-wood skirting")),
    "paving": ("sqft", "civil", 0.22, (5, 7, 14), (85, 160, 380),
        ("Concrete paver", "Natural-stone paver", "Premium stone paving")),
    "turf_landscaping": ("sqft", "gardener", 0.06, (3, 5, 10), (55, 95, 190),
        ("Artificial turf", "Natural lawn with irrigation", "Designed softscape")),
    "outdoor_lighting": ("nos", "electrician", 1.0, (5, 7, 14), (900, 2400, 7500),
        ("Solar bollard light", "Wired garden light", "Architectural outdoor lighting")),
    "pergola": ("sqft", "fabricator", 0.50, (14, 21, 35), (700, 1300, 2800),
        ("MS powder-coated pergola", "Aluminium pergola", "Teak / architectural pergola")),
    "planters": ("nos", "gardener", 0.5, (3, 5, 10), (800, 2200, 6500),
        ("Fibre planter", "Cement planter", "Designer planter")),
    "smart_switches": ("nos", "electrician", 0.8, (5, 7, 14), (1800, 3200, 6500),
        ("Wi-Fi smart switch", "Zigbee smart switch", "Premium smart switch with scenes")),
    "smart_lock": ("nos", "electrician", 1.5, (5, 7, 14), (9000, 17000, 38000),
        ("Smart lock, PIN", "Smart lock, PIN + fingerprint", "Premium smart lock with app audit")),
    "smart_cameras": ("nos", "electrician", 1.2, (3, 5, 10), (3500, 7500, 17000),
        ("1080p Wi-Fi camera", "2K PoE camera", "4K camera with local NVR")),
    "smart_hub": ("nos", "electrician", 1.0, (5, 7, 14), (5000, 9500, 18000),
        ("Basic smart hub", "Zigbee/Matter hub", "Pro automation controller")),
    "smart_lighting": ("nos", "electrician", 0.7, (3, 5, 10), (1500, 3200, 8000),
        ("Smart bulb", "Smart downlight", "Tunable-white smart fixture")),
}

LABOR_RATES: dict[str, float] = {
    "carpenter": 280, "tiler": 260, "painter": 220, "electrician": 300, "plumber": 300,
    "civil": 240, "stone_mason": 320, "fabricator": 350, "gardener": 180,
}

REGIONS: list[tuple[str, str, float, list[str]]] = [
    ("default", "Default (national average)", 1.00, []),
    ("chennai", "Chennai", 0.98, ["chennai", "madras", "tamil nadu"]),
    ("bengaluru", "Bengaluru", 1.08, ["bengaluru", "bangalore", "karnataka"]),
    ("mumbai", "Mumbai", 1.22, ["mumbai", "bombay", "navi mumbai", "thane"]),
    ("delhi_ncr", "Delhi NCR", 1.12, ["delhi", "gurgaon", "gurugram", "noida", "ncr"]),
    ("hyderabad", "Hyderabad", 1.03, ["hyderabad", "telangana", "secunderabad"]),
    ("pune", "Pune", 1.05, ["pune"]),
    ("kolkata", "Kolkata", 0.95, ["kolkata", "calcutta"]),
    ("tier2", "Tier-2 cities", 0.88, ["coimbatore", "madurai", "mysuru", "indore", "jaipur", "kochi", "vizag"]),
]

TIERS = ("budget", "standard", "premium")


def material_rows(currency: str = "INR") -> list[dict]:
    rows = []
    for group, (unit, trade, hrs, leads, prices, names) in MATERIAL_GROUPS.items():
        for i, tier in enumerate(TIERS):
            rows.append({
                "sku": f"{group.upper()}-{tier[:3].upper()}", "group": group, "name": names[i], "tier": tier,
                "unit": unit, "unit_price": prices[i], "currency": currency, "labor_trade": trade,
                "labor_hours_per_unit": hrs, "lead_days": leads[i], "available": True, "is_sample": True,
            })
    return rows
