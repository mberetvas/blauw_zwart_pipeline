"""Synthetic fan master profiles (sidecar JSON)."""

from __future__ import annotations

import random

from fan_events.generation.fan_profiles import (
    AGE_BANDS,
    COUNTRY_REGIONS,
    GENDERS,
    LOYALTY_TIERS,
    build_fans_sidecar,
    derived_seed,
    format_fans_sidecar_json,
    synthetic_fan_profile,
)
from fan_events.generation.v3_retail import (
    generate_retail_batch,
    iter_retail_ndjson_lines,
    retail_stream_ndjson,
)
from fan_events.io.ndjson_io import dumps_canonical


def test_derived_seed_stable_across_calls() -> None:
    assert derived_seed(42, "fan_00001") == derived_seed(42, "fan_00001")
    assert derived_seed(None, "fan_00001") == derived_seed(None, "fan_00001")


def test_derived_seed_differs_by_fan_id_or_seed() -> None:
    assert derived_seed(1, "fan_00001") != derived_seed(1, "fan_00002")
    assert derived_seed(1, "fan_00001") != derived_seed(2, "fan_00001")


def test_synthetic_fan_profile_same_seed_same_dict() -> None:
    a = synthetic_fan_profile("fan_00007", global_seed=99)
    b = synthetic_fan_profile("fan_00007", global_seed=99)
    assert a == b


def test_synthetic_fan_profile_different_seed_differs() -> None:
    a = synthetic_fan_profile("fan_00003", global_seed=1)
    b = synthetic_fan_profile("fan_00003", global_seed=2)
    assert a != b


def test_profile_values_in_closed_sets() -> None:
    p = synthetic_fan_profile("fan_00100", global_seed=123)
    assert p["loyalty_tier"] in LOYALTY_TIERS
    assert p["age_band"] in AGE_BANDS
    assert p["country_region"] in COUNTRY_REGIONS
    assert p["gender"] in GENDERS
    assert p["fan_id"] == "fan_00100"
    assert p["synthetic_full_name"].startswith("Synthetic ")


def test_build_fans_sidecar_sorted_keys_and_empty() -> None:
    doc = build_fans_sidecar([], global_seed=None)
    assert doc["fans"] == {}
    assert doc["rng_seed"] is None
    assert doc["schema_version"] == 1
    text = format_fans_sidecar_json(doc)
    assert text == dumps_canonical(doc) + "\n"

    doc2 = build_fans_sidecar(["fan_00002", "fan_00001"], global_seed=5)
    assert list(doc2["fans"].keys()) == ["fan_00001", "fan_00002"]


def test_loyalty_tier_distribution_loose() -> None:
    """Large fan set: platinum should appear rarely (weight 5%)."""
    ids = [f"fan_{i:05d}" for i in range(1, 4000)]
    doc = build_fans_sidecar(ids, global_seed=2026)
    tiers = [doc["fans"][fid]["loyalty_tier"] for fid in ids]
    assert tiers.count("platinum") >= 1
    assert tiers.count("bronze") > tiers.count("platinum")


def test_iter_retail_ndjson_lines_fan_ids_matches_stream_bytes() -> None:
    kw: dict = {"max_events": 40}
    sink: set[str] = set()
    text = "".join(iter_retail_ndjson_lines(random.Random(5), fan_ids=sink, **kw))
    assert text == retail_stream_ndjson(random.Random(5), **kw)
    ids_from_batch = {r["fan_id"] for r in generate_retail_batch(random.Random(5), **kw)}
    assert sink == ids_from_batch
