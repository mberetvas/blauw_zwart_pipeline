"""Domain constants for synthetic fan events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

# Jan Breydel maximum capacity (spec / contract FR-SC-006).
JAN_BREYDEL_MAX_CAPACITY = 29_062

TICKET_SCAN = "ticket_scan"
MERCH_PURCHASE = "merch_purchase"
RETAIL_PURCHASE = "retail_purchase"

# NDJSON v3 retail — shop ids (ordering matches default weights).
SHOP_JAN_BREYDEL_FAN = "jan_breydel_fan_shop"
SHOP_WEB = "webshop"
SHOP_BRUGES_CITY = "bruges_city_shop"

SHOP_IDS: tuple[str, ...] = (
    SHOP_JAN_BREYDEL_FAN,
    SHOP_WEB,
    SHOP_BRUGES_CITY,
)

SHOP_DISPLAY_NAME: dict[str, str] = {
    SHOP_JAN_BREYDEL_FAN: "Jan Breydel fan shop (in-stadium retail)",
    SHOP_WEB: "Webshop",
    SHOP_BRUGES_CITY: "Bruges city shop",
}

DEFAULT_SHOP_WEIGHTS: tuple[float, float, float] = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)

DEFAULT_RETAIL_SIM_EPOCH_UTC = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def validate_shop_weights(weights: Sequence[float]) -> None:
    """Raise ValueError if weights are not three non-negative floats that sum to > 0."""
    if len(weights) != len(SHOP_IDS):
        raise ValueError(f"shop weights must have length {len(SHOP_IDS)}, got {len(weights)}")
    for w in weights:
        if w < 0:
            raise ValueError("shop weights must be non-negative")
    s = float(sum(weights))
    if s <= 0:
        raise ValueError("shop weights must sum to a positive value")

DEFAULT_SCAN_FRACTION = 0.85
DEFAULT_MERCH_FACTOR = 0.25

LOCATIONS = [
    "Jan Breydel Noord A",
    "Jan Breydel Zuid B",
    "Tribune 3 Gate 7",
    "Fan Zone East",
    "VIP Ingang West",
]

ITEMS = [
    "Beanie 1891 Fisherman zwart",
    "Beanie 1891 grijs",
    "Beanie 1891 navy",
    "Beanie Fan Flag Black",
    "Handschoenen Touch volw.",
    "Pet 'summer pink'",
    "Pet 1891",
    "Pet basic black",
    "Pet Logo Gestreept",
    "Pet Navy Basic",
    "Retro Beanie Assubel",
    "Retro Beanie Wit",
    "Retro Sjaal Assubel",
    "Sjaal Bayern Munchen - Club Brugge",
    "Sjaal Club - RB Salzburg",
    "Sjaal Club Brugge",
    "Sjaal Club Brugge - Arsenal",
    "Sjaal Club Brugge - FC Barcelona",
    "Sjaal Club Kids",
    "Sjaal Fort Jan Breydel",
    "Sjaal No Sweat No Glory",
    "Sjaal You'll never walk alone",
    "Sleutelhanger Beer 10cm",
    "Spiegelhanger 25/26",
]
