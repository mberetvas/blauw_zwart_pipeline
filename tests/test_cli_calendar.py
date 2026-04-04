"""CLI calendar mode argument validation."""

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "generate_fan_events.py"
_FIX = _REPO / "tests" / "fixtures" / "calendar_two_tiny.json"


def test_v2_calendar_all_matches_without_date_range(tmp_path: Path) -> None:
    """Omitting --from-date / --to-date includes every match in the calendar file."""
    out = tmp_path / "all.ndjson"
    subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--calendar",
            str(_FIX),
            "--seed",
            "7",
            "-o",
            str(out),
        ],
        cwd=_REPO,
        check=True,
    )
    text = out.read_text(encoding="utf-8")
    assert text
    assert "m-tiny-home" in text
    assert "m-tiny-away" in text


def test_calendar_only_from_date_rejected() -> None:
    p = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--calendar",
            str(_FIX),
            "--from-date",
            "2026-01-01",
            "-o",
            "out.ndjson",
        ],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "omit both" in (p.stderr or "")


def test_v2_calendar_end_to_end(tmp_path: Path) -> None:
    out = tmp_path / "season.ndjson"
    subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--calendar",
            str(_FIX),
            "--from-date",
            "2026-01-01",
            "--to-date",
            "2027-12-31",
            "--seed",
            "7",
            "-o",
            str(out),
        ],
        cwd=_REPO,
        check=True,
    )
    text = out.read_text(encoding="utf-8")
    assert text
    first = text.strip().split("\n")[0]
    assert '"match_id"' in first


def test_calendar_with_count_rejected() -> None:
    p = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--calendar",
            str(_FIX),
            "--from-date",
            "2026-01-01",
            "--to-date",
            "2027-12-31",
            "-n",
            "5",
            "-o",
            "out.ndjson",
        ],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "cannot be used with --calendar" in (p.stderr or "")
