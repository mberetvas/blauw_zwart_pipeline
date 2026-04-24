"""Structured synthetic catalogs for fan event generation.

- ``MerchItem`` / ``MERCH_ITEMS``: NDJSON ``item`` strings and base EUR prices for
  v1/v2 ``merch_purchase`` and v3 ``retail_purchase``; validated in ``ndjson_io``.
- ``StadiumGate`` / ``LOCATIONS``: ticket scan locations for v1 and v2 home-match scans.
- ``Shop`` / ``SHOPS``: v3 retail shop ids, display names, and default weights (CLI
  ``--shop-weights`` order matches ``SHOP_IDS``).

Fan profile sidecar literals live in ``fan_profiles`` (not NDJSON contracts).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# --- Merch / retail product catalog (NDJSON ``item`` must match ``MerchItem.name``) ---


@dataclass(frozen=True)
class MerchItem:
    """Catalog row: ``name`` is emitted verbatim on NDJSON lines."""

    name: str
    price_eur: float


MERCH_ITEMS: tuple[MerchItem, ...] = (
    MerchItem("Beanie 1891 Fisherman zwart", 29.99),
    MerchItem("Beanie 1891 grijs", 29.99),
    MerchItem("Beanie 1891 navy", 29.99),
    MerchItem("Beanie Fan Flag Black", 27.50),
    MerchItem("Handschoenen Touch volw.", 18.95),
    MerchItem("Pet 'summer pink'", 22.00),
    MerchItem("Pet 1891", 24.95),
    MerchItem("Pet basic black", 19.95),
    MerchItem("Pet Logo Gestreept", 21.50),
    MerchItem("Pet Navy Basic", 21.50),
    MerchItem("Retro Beanie Assubel", 32.00),
    MerchItem("Retro Beanie Wit", 32.00),
    MerchItem("Retro Sjaal Assubel", 34.95),
    MerchItem("Sjaal Bayern Munchen - Club Brugge", 39.95),
    MerchItem("Sjaal Club - RB Salzburg", 39.95),
    MerchItem("Sjaal Club Brugge", 24.95),
    MerchItem("Sjaal Club Brugge - Arsenal", 42.95),
    MerchItem("Sjaal Club Brugge - FC Barcelona", 42.95),
    MerchItem("Sjaal Club Kids", 18.95),
    MerchItem("Sjaal Fort Jan Breydel", 26.95),
    MerchItem("Sjaal No Sweat No Glory", 24.95),
    MerchItem("Sjaal You'll never walk alone", 24.95),
    MerchItem("Sleutelhanger Beer 10cm", 9.95),
    MerchItem("Spiegelhanger 25/26", 14.95),
)

ITEMS: tuple[str, ...] = tuple(m.name for m in MERCH_ITEMS)
MERCH_BY_NAME: dict[str, MerchItem] = {m.name: m for m in MERCH_ITEMS}

# Multiplicative jitter band around ``price_eur`` (one ``randint`` per line, legacy bounds).
_AMOUNT_JITTER_LOW = 0.85
_AMOUNT_JITTER_HIGH = 1.15
SYNTHETIC_LINE_AMOUNT_RANDINT_LOW = 1
SYNTHETIC_LINE_AMOUNT_RANDINT_HIGH = 99_999
_RANDINT_AMOUNT_LOW = SYNTHETIC_LINE_AMOUNT_RANDINT_LOW
_RANDINT_AMOUNT_HIGH = SYNTHETIC_LINE_AMOUNT_RANDINT_HIGH


def line_amount_eur_from_jitter_int(item_name: str, u: int) -> float:
    """EUR line total from catalog ``item_name`` and jitter draw ``u``.

    ``u`` must be in ``[1, 99999]`` (same domain as the legacy merch ``randint``).
    Used by v1 ``one_merch`` so the draw happens **before** fan/item/timestamp,
    matching historical RNG order.
    """
    if u < _RANDINT_AMOUNT_LOW or u > _RANDINT_AMOUNT_HIGH:
        raise ValueError(
            f"jitter draw must be in [{_RANDINT_AMOUNT_LOW}, {_RANDINT_AMOUNT_HIGH}], got {u}"
        )
    item = MERCH_BY_NAME[item_name]
    span = _RANDINT_AMOUNT_HIGH - _RANDINT_AMOUNT_LOW
    t = (u - _RANDINT_AMOUNT_LOW) / span if span else 0.0
    factor = _AMOUNT_JITTER_LOW + t * (_AMOUNT_JITTER_HIGH - _AMOUNT_JITTER_LOW)
    raw = item.price_eur * factor
    return round(max(0.01, raw), 2)


def synthetic_line_amount_eur(item_name: str, rng: random.Random) -> float:
    """EUR line total for merch/retail: catalog price with multiplicative jitter.

    Uses exactly one ``rng.randint(1, 99999)``. v2/v3 call this **after** ``item``
    is chosen (their historical order). v1 uses :func:`line_amount_eur_from_jitter_int`
    with a draw taken **before** fan/item/timestamp.
    """
    u = rng.randint(_RANDINT_AMOUNT_LOW, _RANDINT_AMOUNT_HIGH)
    return line_amount_eur_from_jitter_int(item_name, u)


# --- Stadium / gate locations (v1 ticket_scan, v2 home ticket_scan) ---


@dataclass(frozen=True)
class StadiumGate:
    name: str


STADIUM_GATES: tuple[StadiumGate, ...] = (
    StadiumGate("Jan Breydel Noord A"),
    StadiumGate("Jan Breydel Zuid B"),
    StadiumGate("Tribune 3 Gate 7"),
    StadiumGate("Fan Zone East"),
    StadiumGate("VIP Ingang West"),
)

LOCATIONS: tuple[str, ...] = tuple(g.name for g in STADIUM_GATES)

# --- v3 retail shops ---


@dataclass(frozen=True)
class Shop:
    id: str
    display_name: str
    default_weight: float


SHOP_JAN_BREYDEL_FAN = "jan_breydel_fan_shop"
SHOP_WEB = "webshop"
SHOP_BRUGES_CITY = "bruges_city_shop"

SHOPS: tuple[Shop, ...] = (
    Shop(
        SHOP_JAN_BREYDEL_FAN,
        "Jan Breydel fan shop (in-stadium retail)",
        1.0 / 3.0,
    ),
    Shop(SHOP_WEB, "Webshop", 1.0 / 3.0),
    Shop(SHOP_BRUGES_CITY, "Bruges city shop", 1.0 / 3.0),
)

SHOP_IDS: tuple[str, ...] = tuple(s.id for s in SHOPS)
SHOP_DISPLAY_NAME: dict[str, str] = {s.id: s.display_name for s in SHOPS}
DEFAULT_SHOP_WEIGHTS: tuple[float, float, float] = (
    SHOPS[0].default_weight,
    SHOPS[1].default_weight,
    SHOPS[2].default_weight,
)
