"""Calendar JSON validation (fail-fast)."""

from pathlib import Path

import pytest

from fan_events.generation.v2_calendar import (
    CalendarError,
    load_calendar_json,
    validate_and_parse_matches,
)

_FIX = Path(__file__).resolve().parent / "fixtures" / "calendar_two_tiny.json"


def test_load_valid_calendar() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    assert len(rows) == 2


def test_duplicate_match_id() -> None:
    doc = load_calendar_json(_FIX)
    doc["matches"] = list(doc["matches"]) + [dict(doc["matches"][0])]
    with pytest.raises(CalendarError, match="duplicate"):
        validate_and_parse_matches(doc)


def test_home_attendance_over_capacity() -> None:
    from fan_events.core.domain import JAN_BREYDEL_MAX_CAPACITY

    doc = load_calendar_json(_FIX)
    doc["matches"][0]["attendance"] = JAN_BREYDEL_MAX_CAPACITY + 1
    with pytest.raises(CalendarError, match="exceeds"):
        validate_and_parse_matches(doc)


def test_non_positive_attendance() -> None:
    doc = load_calendar_json(_FIX)
    doc["matches"][0]["attendance"] = 0
    with pytest.raises(CalendarError, match="> 0"):
        validate_and_parse_matches(doc)


def test_encounter_type_must_match_home_away() -> None:
    doc = load_calendar_json(_FIX)
    doc["matches"][0]["encounter_type"] = "away"
    with pytest.raises(CalendarError, match="encounter_type must match home_away"):
        validate_and_parse_matches(doc)


def test_score_fields_must_arrive_as_a_pair() -> None:
    doc = load_calendar_json(_FIX)
    doc["matches"][0]["home_score"] = 2
    with pytest.raises(CalendarError, match="home_score and away_score"):
        validate_and_parse_matches(doc)


def test_home_venue_metadata_capacity_must_be_positive() -> None:
    doc = load_calendar_json(_FIX)
    doc["club_home_venue_metadata"] = {"stadium_capacity": 0}
    with pytest.raises(CalendarError, match="stadium_capacity must be > 0"):
        validate_and_parse_matches(doc)
