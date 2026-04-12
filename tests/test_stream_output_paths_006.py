"""006: stdout vs file append produce identical bytes (fixed seed, caps)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_FIX = _REPO / "tests" / "fixtures" / "calendar_two_tiny.json"


def _env() -> dict[str, str]:
    import os

    e = os.environ.copy()
    e["PYTHONPATH"] = str(_REPO / "src")
    return e


def test_stream_stdout_matches_file_bytes(tmp_path: Path) -> None:
    base = [
        sys.executable,
        "-m",
        "fan_events",
        "stream",
        "--calendar",
        str(_FIX),
        "--no-calendar-loop",
        "--seed",
        "100",
        "--max-events",
        "40",
        "--retail-max-events",
        "25",
    ]
    p_out = subprocess.run(
        [*base],
        cwd=_REPO,
        env=_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    out_path = tmp_path / "s.ndjson"
    subprocess.run(
        [*base, "-o", str(out_path)],
        cwd=_REPO,
        env=_env(),
        check=True,
    )
    assert p_out.stdout == out_path.read_text(encoding="utf-8")
