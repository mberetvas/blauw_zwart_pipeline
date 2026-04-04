"""Golden output for v1 rolling mode (byte-stable with --seed)."""

import os
import random
import subprocess
import sys
from pathlib import Path

from fan_events.ndjson_io import records_to_ndjson_v1
from fan_events.v1_batch import FIXED_NOW_UTC, generate_batch

_FIX = Path(__file__).resolve().parent / "fixtures" / "v1_golden_seed1_n10_d30.ndjson"
_V1_GOLDEN = _FIX.read_text(encoding="utf-8")


def test_v1_generate_matches_golden() -> None:
    rng = random.Random(1)
    records = generate_batch(
        rng,
        count=10,
        days=30,
        events_mode="both",
        now_utc=FIXED_NOW_UTC,
    )
    out = records_to_ndjson_v1(records)
    assert out == _V1_GOLDEN


def test_cli_v1_subprocess_matches_golden(tmp_path: Path) -> None:
    out = tmp_path / "out.ndjson"
    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
            "--seed",
            "1",
            "-n",
            "10",
            "--days",
            "30",
            "-o",
            str(out),
        ],
        cwd=repo,
        env=env,
        check=True,
    )
    assert out.read_text(encoding="utf-8") == _V1_GOLDEN
