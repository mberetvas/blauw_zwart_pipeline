"""Define shared domain constants for synthetic fan-event generation.

This module re-exports the core catalogs from :mod:`fan_events.core.data` so
the rest of the package can import one stable domain surface. It also defines
event-type constants, default simulation anchors, and validation helpers used
by the CLI and generation pipelines.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

import fan_events.core.data as _data

# Catalogs (single source: ``fan_events.core.data``).
# Exposed for ``from fan_events.core.domain import …``.
DEFAULT_SHOP_WEIGHTS = _data.DEFAULT_SHOP_WEIGHTS
ITEMS = _data.ITEMS
LOCATIONS = _data.LOCATIONS
SHOP_BRUGES_CITY = _data.SHOP_BRUGES_CITY
SHOP_DISPLAY_NAME = _data.SHOP_DISPLAY_NAME
SHOP_IDS = _data.SHOP_IDS
SHOP_JAN_BREYDEL_FAN = _data.SHOP_JAN_BREYDEL_FAN
SHOP_WEB = _data.SHOP_WEB

# Jan Breydel maximum capacity (spec / contract FR-SC-006).
JAN_BREYDEL_MAX_CAPACITY = 29_062

TICKET_SCAN = "ticket_scan"
MERCH_PURCHASE = "merch_purchase"
RETAIL_PURCHASE = "retail_purchase"

DEFAULT_RETAIL_SIM_EPOCH_UTC = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def validate_shop_weights(weights: Sequence[float]) -> None:
    """Validate the three retail shop weights used by v3 generation.

    Args:
        weights: Sequence of weights whose positional order must match
            :data:`SHOP_IDS`.

    Raises:
        ValueError: If the number of weights is wrong, any weight is negative,
            or the sequence sums to zero.
    """
    # The CLI accepts bare numeric lists, so enforce the positional contract
    # here before weighted sampling happens deeper in the generator.
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
