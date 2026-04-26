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
    """Describe one merch catalog entry used by event generators.

    Attributes:
        name: Canonical item label emitted verbatim on NDJSON records.
        price_eur: Base catalog price before synthetic jitter is applied.
    """

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
    """Derive a deterministic EUR amount from a catalog item and jitter draw.

    Args:
        item_name: Catalog item name present in :data:`MERCH_BY_NAME`.
        u: Legacy ``randint`` draw in the inclusive range ``[1, 99999]``.

    Returns:
        Rounded line amount in EUR, clipped to at least ``0.01``.

    Raises:
        ValueError: If ``u`` falls outside the legacy jitter domain.

    Note:
        v1 uses this helper so the jitter draw happens before fan, item, and
        timestamp selection, preserving the historical RNG order.
    """
    if u < _RANDINT_AMOUNT_LOW or u > _RANDINT_AMOUNT_HIGH:
        raise ValueError(f"jitter draw must be in [{_RANDINT_AMOUNT_LOW}, {_RANDINT_AMOUNT_HIGH}], got {u}")
    item = MERCH_BY_NAME[item_name]
    span = _RANDINT_AMOUNT_HIGH - _RANDINT_AMOUNT_LOW
    # Convert the legacy randint domain into a linear factor inside the jitter
    # band so existing golden outputs stay byte-stable.
    t = (u - _RANDINT_AMOUNT_LOW) / span if span else 0.0
    factor = _AMOUNT_JITTER_LOW + t * (_AMOUNT_JITTER_HIGH - _AMOUNT_JITTER_LOW)
    raw = item.price_eur * factor
    return round(max(0.01, raw), 2)


def synthetic_line_amount_eur(item_name: str, rng: random.Random) -> float:
    """Return a synthetic EUR amount for one merch or retail line item.

    Args:
        item_name: Catalog item name present in :data:`MERCH_BY_NAME`.
        rng: Random generator responsible for reproducible draw order.

    Returns:
        Rounded line amount in EUR after multiplicative jitter is applied.

    Note:
        This helper consumes exactly one ``rng.randint(1, 99999)`` draw. v2 and
        v3 call it after the item choice; v1 preserves its older order by using
        :func:`line_amount_eur_from_jitter_int` with a pre-drawn integer.
    """
    u = rng.randint(_RANDINT_AMOUNT_LOW, _RANDINT_AMOUNT_HIGH)
    return line_amount_eur_from_jitter_int(item_name, u)


# --- Stadium / gate locations (v1 ticket_scan, v2 home ticket_scan) ---


@dataclass(frozen=True)
class StadiumGate:
    """Describe one stadium gate label used on ticket-scan events.

    Attributes:
        name: Human-readable gate or zone label emitted on scan records.
    """

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
    """Describe one retail outlet used by v3 purchase generation.

    Attributes:
        id: Stable machine identifier written to NDJSON records.
        display_name: Human-readable label used in docs and UI surfaces.
        default_weight: Default weighted-sampling share for this outlet.
    """

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
