"""Catalog and synthetic amount helper (fan_events.data)."""

from __future__ import annotations

import random

import pytest

from fan_events.data import (
    ITEMS,
    MERCH_BY_NAME,
    MERCH_ITEMS,
    line_amount_eur_from_jitter_int,
    synthetic_line_amount_eur,
)


def test_merch_items_cover_items_tuple() -> None:
    assert tuple(m.name for m in MERCH_ITEMS) == ITEMS
    assert len(MERCH_BY_NAME) == len(ITEMS)


def test_synthetic_line_amount_eur_positive_two_decimals() -> None:
    rng = random.Random(0)
    name = ITEMS[0]
    amt = synthetic_line_amount_eur(name, rng)
    assert amt > 0
    assert round(amt, 2) == amt
    base = MERCH_BY_NAME[name].price_eur
    assert 0.85 * base - 0.02 <= amt <= 1.15 * base + 0.02


def test_synthetic_line_amount_unknown_item() -> None:
    with pytest.raises(KeyError):
        synthetic_line_amount_eur("not a catalog item", random.Random(0))


def test_synthetic_line_amount_reproducible() -> None:
    a = synthetic_line_amount_eur(ITEMS[3], random.Random(42))
    b = synthetic_line_amount_eur(ITEMS[3], random.Random(42))
    assert a == b


def test_line_amount_from_jitter_matches_synthetic_for_same_draw() -> None:
    name = ITEMS[5]
    u = 48_291

    class _RngOneInt:
        def randint(self, low: int, high: int) -> int:
            assert low == 1 and high == 99_999
            return u

    assert line_amount_eur_from_jitter_int(name, u) == synthetic_line_amount_eur(
        name, _RngOneInt()
    )


def test_line_amount_from_jitter_int_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="jitter draw"):
        line_amount_eur_from_jitter_int(ITEMS[0], 0)
    with pytest.raises(ValueError, match="jitter draw"):
        line_amount_eur_from_jitter_int(ITEMS[0], 100_000)
