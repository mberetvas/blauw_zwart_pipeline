"""Canonical NDJSON serialization and atomic file writes."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fan_events.core.data import ITEMS, SHOP_IDS
from fan_events.core.domain import MERCH_PURCHASE, RETAIL_PURCHASE, TICKET_SCAN


_V2_OPTIONAL_MATCH_FIELDS = frozenset(
    {
        "kickoff_local",
        "timezone",
        "attendance",
        "home_away",
        "encounter_type",
        "opponent",
        "home_score",
        "away_score",
        "venue_label",
        "club_home_club",
        "club_home_stadium",
        "club_home_stadium_capacity",
        "club_home_reported_total_attendance",
        "club_home_reported_average_attendance",
        "club_home_reported_home_matches",
        "club_home_reported_sold_out_matches",
        "club_home_reported_capacity_pct",
    }
)


def _validate_allowed_keys(*, rec: dict[str, Any], required: set[str], optional: set[str], label: str) -> None:
    keys = set(rec.keys())
    missing = required - keys
    invalid = keys - required - optional
    if missing:
        raise ValueError(f"{label} missing required keys: {sorted(missing)}")
    if invalid:
        raise ValueError(f"{label} has invalid keys: {sorted(invalid)}")


def _validate_optional_v2_match_fields(rec: dict[str, Any]) -> None:
    for key in (
        "kickoff_local",
        "timezone",
        "opponent",
        "venue_label",
        "club_home_club",
        "club_home_stadium",
    ):
        if key in rec and (not isinstance(rec[key], str) or not rec[key]):
            raise ValueError(f"v2 record: {key} must be a non-empty string when present")

    for key in (
        "attendance",
        "home_score",
        "away_score",
        "club_home_stadium_capacity",
        "club_home_reported_total_attendance",
        "club_home_reported_average_attendance",
        "club_home_reported_home_matches",
        "club_home_reported_sold_out_matches",
    ):
        if key in rec:
            val = rec[key]
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValueError(f"v2 record: {key} must be an integer when present")
            if val < 0:
                raise ValueError(f"v2 record: {key} must be >= 0 when present")

    for key in ("home_away", "encounter_type"):
        if key in rec and rec[key] not in ("home", "away"):
            raise ValueError(f"v2 record: {key} must be 'home' or 'away' when present")

    if "club_home_reported_capacity_pct" in rec:
        pct = rec["club_home_reported_capacity_pct"]
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            raise ValueError("v2 record: club_home_reported_capacity_pct must be numeric")


def dumps_canonical(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_atomic_text(path: Path, content: str) -> None:
    path = path.resolve()
    ensure_parent_dir(path)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as tf:
            tf.write(content)
            tmp_name = tf.name
        os.replace(tmp_name, path)
        tmp_name = None
    except Exception:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise


def validate_record_v1(rec: dict[str, Any]) -> None:
    if not isinstance(rec, dict):
        raise ValueError("record must be a dict")
    ev = rec.get("event")
    if ev == TICKET_SCAN:
        allowed = {"event", "fan_id", "location", "timestamp"}
        if set(rec.keys()) != allowed:
            raise ValueError(f"ticket_scan must have exactly keys {sorted(allowed)}")
        if not rec["fan_id"] or not rec["location"] or not rec["timestamp"]:
            raise ValueError("ticket_scan: fan_id, location, timestamp must be non-empty")
    elif ev == MERCH_PURCHASE:
        allowed = {"amount", "event", "fan_id", "item", "timestamp"}
        if set(rec.keys()) != allowed:
            raise ValueError(f"merch_purchase must have exactly keys {sorted(allowed)}")
        if not rec["fan_id"] or not rec["item"] or not rec["timestamp"]:
            raise ValueError("merch_purchase: fan_id, item, timestamp must be non-empty")
        amt = rec["amount"]
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError("merch_purchase: amount must be a number")
        if amt <= 0:
            raise ValueError("merch_purchase: amount must be > 0")
    else:
        raise ValueError(f"unknown event: {ev!r}")


def _event_rank(event: str) -> int:
    if event == TICKET_SCAN:
        return 0
    if event == MERCH_PURCHASE:
        return 1
    raise ValueError(f"unknown event for rank: {event!r}")


def sort_key_v1(rec: dict[str, Any]) -> tuple:
    ev = rec["event"]
    ts = rec["timestamp"]
    fan = rec["fan_id"]
    rank = _event_rank(ev)
    if ev == TICKET_SCAN:
        return (ts, rank, fan, rec["location"], "", 0.0)
    return (ts, rank, fan, "", rec["item"], float(rec["amount"]))


def records_to_ndjson_v1(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    for rec in records:
        validate_record_v1(rec)
    ordered = sorted(records, key=sort_key_v1)
    lines = [dumps_canonical(r) for r in ordered]
    body = "\n".join(lines)
    return body + "\n"


def validate_record_v2(rec: dict[str, Any]) -> None:
    if not isinstance(rec, dict):
        raise ValueError("record must be a dict")
    ev = rec.get("event")
    if ev == TICKET_SCAN:
        required = {"event", "fan_id", "location", "match_id", "timestamp"}
        _validate_allowed_keys(
            rec=rec,
            required=required,
            optional=set(_V2_OPTIONAL_MATCH_FIELDS),
            label="v2 ticket_scan",
        )
        for k in ("fan_id", "location", "match_id", "timestamp"):
            if not rec[k]:
                raise ValueError(f"v2 ticket_scan: {k} must be non-empty")
        _validate_optional_v2_match_fields(rec)
    elif ev == MERCH_PURCHASE:
        base = {"amount", "event", "fan_id", "item", "match_id", "timestamp"}
        _validate_allowed_keys(
            rec=rec,
            required=base,
            optional=set(_V2_OPTIONAL_MATCH_FIELDS) | {"location"},
            label="v2 merch_purchase",
        )
        for k in ("fan_id", "item", "match_id", "timestamp"):
            if not rec[k]:
                raise ValueError(f"v2 merch_purchase: {k} must be non-empty")
        if "location" in rec and not rec["location"]:
            raise ValueError("v2 merch_purchase: location if present must be non-empty")
        amt = rec["amount"]
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError("merch_purchase: amount must be a number")
        if amt <= 0:
            raise ValueError("merch_purchase: amount must be > 0")
        _validate_optional_v2_match_fields(rec)
    else:
        raise ValueError(f"unknown event: {ev!r}")


def sort_key_v2(rec: dict[str, Any]) -> tuple:
    """Global sort per fan-events-ndjson-v2.md."""
    ev = rec["event"]
    ts = rec["timestamp"]
    fan = rec["fan_id"]
    mid = rec["match_id"]
    er = _event_rank(ev)
    if ev == TICKET_SCAN:
        return (ts, er, fan, mid, rec["location"])
    loc = rec.get("location", "")
    return (ts, er, fan, mid, rec["item"], float(rec["amount"]), loc)


def format_line_v2(rec: dict[str, Any]) -> str:
    """One NDJSON line (LF-terminated) for v2 stream mode."""
    validate_record_v2(rec)
    return dumps_canonical(rec) + "\n"


def records_to_ndjson_v2(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    for rec in records:
        validate_record_v2(rec)
    ordered = sorted(records, key=sort_key_v2)
    lines = [dumps_canonical(r) for r in ordered]
    body = "\n".join(lines)
    return body + "\n"


_ITEMS_SET = frozenset(ITEMS)
_SHOP_SET = frozenset(SHOP_IDS)


def _validate_timestamp_utc_z(ts: str) -> None:
    if not isinstance(ts, str) or not ts.endswith("Z"):
        raise ValueError("retail_purchase: timestamp must be a string ending with Z")
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("retail_purchase: timestamp must be valid UTC ISO-8601 with Z") from e


def validate_record_v3(rec: dict[str, Any]) -> None:
    """fan-events-ndjson-v3.md: closed schema retail_purchase only."""
    if not isinstance(rec, dict):
        raise ValueError("record must be a dict")
    allowed = {"amount", "event", "fan_id", "item", "shop", "timestamp"}
    if set(rec.keys()) != allowed:
        raise ValueError(f"retail_purchase must have exactly keys {sorted(allowed)}")
    ev = rec.get("event")
    if ev != RETAIL_PURCHASE:
        raise ValueError(f"retail_purchase: event must be {RETAIL_PURCHASE!r}, got {ev!r}")
    if not rec["fan_id"] or not isinstance(rec["fan_id"], str):
        raise ValueError("retail_purchase: fan_id must be a non-empty string")
    if not rec["item"] or not isinstance(rec["item"], str):
        raise ValueError("retail_purchase: item must be a non-empty string")
    if rec["item"] not in _ITEMS_SET:
        raise ValueError("retail_purchase: item must be in ITEMS catalog")
    shop = rec["shop"]
    if not isinstance(shop, str) or shop not in _SHOP_SET:
        raise ValueError("retail_purchase: shop must be one of SHOP_IDS")
    amt = rec["amount"]
    if not isinstance(amt, (int, float)) or isinstance(amt, bool):
        raise ValueError("retail_purchase: amount must be a number")
    if amt <= 0:
        raise ValueError("retail_purchase: amount must be > 0")
    _validate_timestamp_utc_z(rec["timestamp"])


def sort_key_v3(rec: dict[str, Any]) -> tuple:
    """Global batch sort per fan-events-ndjson-v3.md."""
    return (
        rec["timestamp"],
        rec["event"],
        rec["fan_id"],
        rec["shop"],
        rec["item"],
        float(rec["amount"]),
    )


def records_to_ndjson_v3(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    for rec in records:
        validate_record_v3(rec)
    ordered = sorted(records, key=sort_key_v3)
    lines = [dumps_canonical(r) for r in ordered]
    body = "\n".join(lines)
    return body + "\n"


def format_line_v3(rec: dict[str, Any]) -> str:
    """One NDJSON line (LF-terminated) for stream mode."""
    validate_record_v3(rec)
    return dumps_canonical(rec) + "\n"
