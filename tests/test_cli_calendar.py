"""CLI calendar mode argument validation."""

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_FIX = _REPO / "tests" / "fixtures" / "calendar_two_tiny.json"


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO / "src")
    return env


def test_v2_calendar_all_matches_without_date_range(tmp_path: Path) -> None:
    """Omitting --from-date / --to-date includes every match in the calendar file."""
    out = tmp_path / "all.ndjson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
            "--calendar",
            str(_FIX),
            "--seed",
            "7",
            "-o",
            str(out),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
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
            "-m",
            "fan_events",
            "generate_events",
            "--calendar",
            str(_FIX),
            "--from-date",
            "2026-01-01",
            "-o",
            "out.ndjson",
        ],
        cwd=_REPO,
        env=_subprocess_env(),
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
            "-m",
            "fan_events",
            "generate_events",
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
        env=_subprocess_env(),
        check=True,
    )
    text = out.read_text(encoding="utf-8")
    assert text
    first = text.strip().split("\n")[0]
    assert '"match_id"' in first


def test_v2_calendar_accepts_calendar_path_token_dash_n(tmp_path: Path) -> None:
    """A calendar file whose path is the token ``-n`` must not be confused with ``-n``/count."""
    cal = tmp_path / "-n"
    cal.write_text(_FIX.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out.ndjson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
            "--calendar",
            str(cal),
            "--seed",
            "7",
            "-o",
            str(out),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    assert out.read_text(encoding="utf-8").strip()


def test_calendar_with_count_rejected() -> None:
    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
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
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "cannot be used with --calendar" in (p.stderr or "")
