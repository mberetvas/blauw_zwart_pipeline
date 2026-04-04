"""Calendar JSON validation (fail-fast)."""

from pathlib import Path

import pytest

from fan_events.v2_calendar import CalendarError, load_calendar_json, validate_and_parse_matches

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
    from fan_events.domain import JAN_BREYDEL_MAX_CAPACITY

    doc = load_calendar_json(_FIX)
    doc["matches"][0]["attendance"] = JAN_BREYDEL_MAX_CAPACITY + 1
    with pytest.raises(CalendarError, match="exceeds"):
        validate_and_parse_matches(doc)


def test_non_positive_attendance() -> None:
    doc = load_calendar_json(_FIX)
    doc["matches"][0]["attendance"] = 0
    with pytest.raises(CalendarError, match="> 0"):
        validate_and_parse_matches(doc)
