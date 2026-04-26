"""Synthetic fan master profiles for optional sidecar JSON (not part of NDJSON contracts).

Profiles are derived with a **separate** RNG from event generation so v3 retail draw order
(inter-arrival → shop → item → amount → fan_id) is unchanged.

Per-profile RNG seed: SHA-256 over a UTF-8 payload, first 8 bytes as unsigned big-endian int
(mod 2**63 for ``random.Random`` portability). Payload when ``global_seed`` is set:
``f"{global_seed}\\0{fan_id}"``. When ``global_seed`` is ``None``:
``b"\\0" + fan_id.encode("utf-8")``.

**Profile field draw order** (one ``random.Random`` per fan, in this order only):
1. ``loyalty_tier`` — weighted choice
2. ``age_band`` — weighted choice
3. ``country_region`` — weighted choice
4. ``gender`` — weighted choice
5. ``given_name`` — index into ``GIVEN_NAMES``
6. ``family_name`` — index into ``FAMILY_NAMES``
7. ``synthetic_full_name`` — formatted string (no extra RNG)

**Loyalty tier** weights (must sum to 1.0): bronze **0.50**, silver **0.30**, gold **0.15**,
platinum **0.05**.

**Age band** weights: under_18 **0.08**, 18_25 **0.18**, 26_35 **0.22**, 36_45 **0.20**,
46_55 **0.17**, 56_plus **0.15**.

**Country / region** weights: BE-FL **0.45**, BE-WAL **0.12**, BE-BRU **0.08**, NL **0.15**,
FR **0.08**, DE **0.07**, OTHER **0.05**.

**Gender** weights: female **0.15**, male **0.15**, non_binary **0.10**, prefer_not_to_say **0.60**.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Iterable

from fan_events.io.ndjson_io import dumps_canonical

LOYALTY_TIERS: tuple[str, ...] = ("bronze", "silver", "gold", "platinum")
LOYALTY_WEIGHTS: tuple[float, float, float, float] = (0.50, 0.30, 0.15, 0.05)

AGE_BANDS: tuple[str, ...] = (
    "under_18",
    "18_25",
    "26_35",
    "36_45",
    "46_55",
    "56_plus",
)
AGE_WEIGHTS: tuple[float, ...] = (0.08, 0.18, 0.22, 0.20, 0.17, 0.15)

COUNTRY_REGIONS: tuple[str, ...] = ("BE-FL", "BE-WAL", "BE-BRU", "NL", "FR", "DE", "OTHER")
COUNTRY_REGION_WEIGHTS: tuple[float, ...] = (0.45, 0.12, 0.08, 0.15, 0.08, 0.07, 0.05)

GENDERS: tuple[str, ...] = ("female", "male", "non_binary", "prefer_not_to_say")
GENDER_WEIGHTS: tuple[float, float, float, float] = (0.15, 0.15, 0.10, 0.60)

# Obviously synthetic tokens (QA / fixtures — not real-person names).
GIVEN_NAMES: tuple[str, ...] = (
    "Quinlex",
    "Vexa",
    "Nym",
    "Jorple",
    "Tevix",
    "Muxa",
    "Zephir",
    "Orix",
    "Fael",
    "Kessa",
    "Briv",
    "Yulon",
    "Sarn",
    "Plexa",
    "Dorim",
    "Lunix",
    "Cavor",
    "Heska",
    "Rinex",
    "Molov",
)

FAMILY_NAMES: tuple[str, ...] = (
    "Testuser",
    "Fixturesson",
    "Mockley",
    "Sampleton",
    "Dummyvale",
    "Stubbins",
    "Fakerson",
    "Placeholder",
    "Sandbox",
    "Qauser",
    "Nodata",
    "Voidberg",
    "Nullman",
    "Example",
    "Demo",
)


def derived_seed(global_seed: int | None, fan_id: str) -> int:
    """Derive a deterministic RNG seed for one synthetic fan profile.

    Args:
        global_seed: Optional run-level seed that namespaces all derived fan
            seeds. ``None`` still yields a deterministic per-fan value.
        fan_id: Synthetic fan identifier such as ``fan_00042``.

    Returns:
        Stable integer seed suitable for ``random.Random``.

    Note:
        The implementation uses SHA-256 instead of Python's built-in ``hash`` so
        results stay stable regardless of ``PYTHONHASHSEED``.
    """
    if global_seed is not None:
        payload = f"{global_seed}\0{fan_id}".encode("utf-8")
    else:
        payload = b"\0" + fan_id.encode("utf-8")
    h = hashlib.sha256(payload).digest()
    return int.from_bytes(h[:8], "big") % (2**63)


def _pick_w(rng: random.Random, values: tuple[str, ...], weights: tuple[float, ...]) -> str:
    """Return one weighted choice from a tuple of literal profile values."""
    return rng.choices(list(values), weights=list(weights), k=1)[0]


def synthetic_fan_profile(fan_id: str, *, global_seed: int | None) -> dict[str, Any]:
    """Build one deterministic synthetic fan profile.

    Args:
        fan_id: Synthetic fan identifier to embed in the profile document.
        global_seed: Optional run-level seed that keeps an entire sidecar stable
            across repeated runs.

    Returns:
        Canonical profile dictionary containing demographic buckets and a
        synthetic full name.
    """
    rng = random.Random(derived_seed(global_seed, fan_id))
    # Draw fields in the documented order so fixture outputs remain stable.
    loyalty_tier = _pick_w(rng, LOYALTY_TIERS, LOYALTY_WEIGHTS)
    age_band = _pick_w(rng, AGE_BANDS, AGE_WEIGHTS)
    country_region = _pick_w(rng, COUNTRY_REGIONS, COUNTRY_REGION_WEIGHTS)
    gender = _pick_w(rng, GENDERS, GENDER_WEIGHTS)
    given = GIVEN_NAMES[rng.randrange(0, len(GIVEN_NAMES))]
    family = FAMILY_NAMES[rng.randrange(0, len(FAMILY_NAMES))]
    synthetic_full_name = f"Synthetic {given} {family}"
    return {
        "age_band": age_band,
        "country_region": country_region,
        "fan_id": fan_id,
        "gender": gender,
        "loyalty_tier": loyalty_tier,
        "synthetic_full_name": synthetic_full_name,
    }


def build_fans_sidecar(fan_ids: Iterable[str], *, global_seed: int | None) -> dict[str, Any]:
    """Build the top-level sidecar document for a set of fan IDs.

    Args:
        fan_ids: Iterable of synthetic fan identifiers referenced by generated
            events.
        global_seed: Optional run-level seed recorded in the output document.

    Returns:
        Dictionary with ``schema_version``, ``rng_seed``, and a ``fans`` map of
        per-fan profile documents.
    """
    # Deduplicate and sort so the sidecar is stable regardless of caller order.
    unique = sorted(set(fan_ids))
    fans = {fid: synthetic_fan_profile(fid, global_seed=global_seed) for fid in unique}
    return {
        "fans": fans,
        "rng_seed": global_seed,
        "schema_version": 1,
    }


def format_fans_sidecar_json(doc: dict[str, Any]) -> str:
    """Serialize a fan-profile sidecar document as canonical JSON text.

    Args:
        doc: Sidecar document returned by :func:`build_fans_sidecar`.

    Returns:
        Canonical UTF-8 JSON text terminated by a single trailing newline.
    """
    return dumps_canonical(doc) + "\n"
