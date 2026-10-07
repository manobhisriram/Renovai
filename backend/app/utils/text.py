"""Deterministic text parsing helpers (money, area, timeline, style, rooms)."""

from __future__ import annotations

import re

from app.pricing.seed_data import REGIONS

_MULT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7,
         "k": 1e3, "thousand": 1e3, "million": 1e6, "m": 1e6}
_MONEY = re.compile(
    r"(?P<cur>₹|rs\.?|inr|\$|usd|eur|€|£|gbp)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>lakhs?|lacs?|crores?|cr|thousand|million|k|l|m)?\b",
    re.IGNORECASE,
)
_CURRENCY = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}


def parse_money(text: str, default_currency: str = "INR") -> tuple[float, str] | None:
    """Find a budget figure. Prefers numbers near the word 'budget'; supports lakh/crore/k."""
    low = text.lower()
    anchors = [m.start() for m in re.finditer(r"budget|spend|afford|upto|up to|under|max|within|around|about", low)]
    candidates = []
    for m in _MONEY.finditer(text):
        num = float(m.group("num").replace(",", ""))
        mult = (m.group("mult") or "").lower()
        cur = (m.group("cur") or "").lower()
        # skip bare small numbers that are probably counts/areas/weeks
        trailing = low[m.end(): m.end() + 14]
        if re.match(r"\s*(weeks?|months?|days?|sq|square|sqft|sqm|bhk|rooms?|bed|bath|years?|feet|ft|m2)", trailing):
            continue
        if not mult and not cur and num < 1000:
            continue
        value = num * _MULT.get(mult, 1)
        near = any(0 <= m.start() - a <= 40 for a in anchors)
        candidates.append((near, value, _CURRENCY.get(cur, default_currency)))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (not c[0],))
    _, value, currency = candidates[0]
    return value, currency


def parse_timeline_weeks(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(weeks?|wks?|months?|days?)", text, re.IGNORECASE)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    if unit.startswith("month"):
        return round(n * 4.345, 1)
    if unit.startswith("day"):
        return round(n / 7, 1)
    return n


def parse_area_sqm(text: str) -> float | None:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(sq\.?\s*ft|sqft|square\s*feet|sft|sq\.?\s*m|sqm|square\s*met(?:er|re)s?|m2|m²)", text, re.IGNORECASE)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower().replace(" ", "").replace(".", "")
    if unit in ("sqft", "squarefeet", "sft"):
        return round(n / 10.7639, 1)
    return n


STYLES = ["minimalist", "modern", "contemporary", "traditional", "industrial", "scandinavian", "rustic", "luxury",
          "bohemian", "japandi", "mid-century", "classic", "coastal", "art deco"]
ROOM_WORDS = {"kitchen": "kitchen", "bathroom": "bathroom", "toilet": "bathroom", "washroom": "bathroom",
              "living room": "living room", "hall": "living room", "bedroom": "bedroom", "master bedroom": "master bedroom",
              "balcony": "balcony", "terrace": "terrace", "garden": "garden", "dining": "dining area", "study": "study",
              "pooja": "pooja room", "kids room": "kids room"}


def find_styles(text: str) -> list[str]:
    low = text.lower()
    return [s for s in STYLES if s in low]


def find_rooms(text: str) -> list[str]:
    low = text.lower()
    found: list[str] = []
    for word, room in ROOM_WORDS.items():
        if word in low and room not in found:
            found.append(room)
    return found


def find_location(text: str) -> str | None:
    low = text.lower()
    for _key, display, _mult, aliases in REGIONS:
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", low):
                return display if display and _key != "default" else alias.title()
    m = re.search(r"\b(?:in|at|near)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)", text)
    return m.group(1) if m else None


def find_property_type(text: str) -> str | None:
    m = re.search(r"\b(\d)\s*-?\s*bhk\b", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}BHK apartment"
    for word in ("villa", "apartment", "flat", "penthouse", "office", "house", "studio"):
        if word in text.lower():
            return word
    return None
