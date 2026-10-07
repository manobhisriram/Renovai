from __future__ import annotations

import pytest

from app.utils import text as T


@pytest.mark.parametrize("text,expected", [
    ("budget around 8 lakh", (800000, "INR")),
    ("My budget is 1.5 crore", (15000000, "INR")),
    ("I can spend ₹4,50,000", (450000, "INR")),
    ("budget 50k", (50000, "INR")),
    ("budget of $12,000", (12000, "USD")),
    ("under 6 lakhs please", (600000, "INR")),
])
def test_parse_money(text, expected):
    assert T.parse_money(text) == expected


def test_parse_money_ignores_areas_weeks_and_counts():
    assert T.parse_money("a 120 sq ft kitchen, 6 weeks, 2 bhk") is None
    assert T.parse_money("120 sqft kitchen with budget 8 lakh in 6 weeks")[0] == 800000


@pytest.mark.parametrize("text,expected", [("finish in 6 weeks", 6), ("within 2 months", 8.7), ("in 14 days", 2.0)])
def test_parse_timeline(text, expected):
    assert T.parse_timeline_weeks(text) == expected


def test_parse_area_units():
    assert T.parse_area_sqm("about 120 sq ft") == pytest.approx(11.1, abs=0.1)
    assert T.parse_area_sqm("12 sqm room") == 12
    assert T.parse_area_sqm("no numbers here") is None


def test_style_room_location_property():
    assert T.find_styles("a modern minimalist look") == ["minimalist", "modern"] or set(T.find_styles("a modern minimalist look")) == {"modern", "minimalist"}
    assert "kitchen" in T.find_rooms("redo kitchen and the toilet") and "bathroom" in T.find_rooms("redo kitchen and the toilet")
    assert T.find_location("flat in Bangalore") == "Bengaluru"
    assert T.find_property_type("my 3 BHK flat") == "3BHK apartment"
