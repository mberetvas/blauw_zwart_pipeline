"""v2 generation, reproducibility, grouping, empty range."""

import json
import random
from datetime import date
from pathlib import Path

from fan_events.core.domain import MERCH_PURCHASE, TICKET_SCAN
from fan_events.generation.v2_calendar import (
    filter_matches_by_date_range,
    generate_v2_records,
    load_calendar_json,
    validate_and_parse_matches,
)
from fan_events.io.ndjson_io import records_to_ndjson_v2, validate_record_v2

_FIX = Path(__file__).resolve().parent / "fixtures" / "calendar_two_tiny.json"
_THREE = Path(__file__).resolve().parent / "fixtures" / "calendar_three_matches.json"


def test_three_matches_date_filter_count() -> None:
    doc = load_calendar_json(_THREE)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 9, 1), date(2026, 9, 30))
    assert len(ctx) == 2


def test_empty_filter_yields_zero_byte_ndjson() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2020, 1, 1), date(2020, 1, 2))
    assert ctx == []
    assert records_to_ndjson_v2([]) == ""


def test_v2_reproducibility() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng1 = random.Random(99)
    rng2 = random.Random(99)
    a = records_to_ndjson_v2(generate_v2_records(ctx, rng1))
    b = records_to_ndjson_v2(generate_v2_records(ctx, rng2))
    assert a == b
    assert len(a) > 0


def test_v2_match_ids_present() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(1)
    text = records_to_ndjson_v2(generate_v2_records(ctx, rng))
    mids = {"m-tiny-home", "m-tiny-away"}
    for line in text.strip().split("\n"):
        o = json.loads(line)
        assert o["match_id"] in mids
        validate_record_v2(o)


def test_merch_has_location_for_away_and_home() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(3)
    recs = generate_v2_records(ctx, rng)
    merch = [r for r in recs if r["event"] == MERCH_PURCHASE]
    assert merch
    for r in merch:
        assert r.get("location")


def test_ticket_scan_shape() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(2)
    recs = generate_v2_records(ctx, rng)
    for r in recs:
        if r["event"] == TICKET_SCAN:
            assert {
                "event",
                "fan_id",
                "location",
                "match_id",
                "timestamp",
                "kickoff_local",
                "timezone",
                "attendance",
                "home_away",
                "venue_label",
            }.issubset(r.keys())


def test_optional_calendar_metadata_propagates_to_v2_records() -> None:
    doc = load_calendar_json(_FIX)
    doc["club_home_venue_metadata"] = {
        "club": "Club Brugge",
        "stadium": "Jan Breydelstadion",
        "stadium_capacity": 29062,
        "reported_total_attendance": 343759,
        "reported_average_attendance": 22917,
        "reported_home_matches": 15,
        "reported_sold_out_matches": 1,
        "reported_capacity_pct": 78.9,
    }
    doc["matches"][0]["opponent"] = "Tiny Genk"
    doc["matches"][0]["encounter_type"] = "home"
    doc["matches"][0]["home_score"] = 2
    doc["matches"][0]["away_score"] = 1
    doc["matches"][1]["opponent"] = "Tiny Away"
    doc["matches"][1]["encounter_type"] = "away"
    doc["matches"][1]["home_score"] = 0
    doc["matches"][1]["away_score"] = 1

    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(5)
    recs = generate_v2_records(ctx, rng)

    home_rec = next(r for r in recs if r["match_id"] == "m-tiny-home")
    away_rec = next(r for r in recs if r["match_id"] == "m-tiny-away")

    assert home_rec["opponent"] == "Tiny Genk"
    assert home_rec["encounter_type"] == "home"
    assert home_rec["home_score"] == 2
    assert home_rec["away_score"] == 1
    assert home_rec["club_home_stadium_capacity"] == 29062
    assert home_rec["club_home_reported_capacity_pct"] == 78.9

    assert away_rec["opponent"] == "Tiny Away"
    assert away_rec["encounter_type"] == "away"
    assert away_rec["club_home_stadium"] == "Jan Breydelstadion"
