"""CLI: ``fan_events stream`` (sources matrix, validation, errors)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from fan_events.cli import SUBCOMMAND_STREAM, parse_args, run_stream

_REPO = Path(__file__).resolve().parents[1]
_FIX = _REPO / "tests" / "fixtures" / "calendar_two_tiny.json"


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO / "src")
    return env


def test_parse_stream_post_merge_long_names_only() -> None:
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--seed",
            "1",
            "--max-events",
            "10",
            "--max-duration",
            "3600",
            "--retail-max-events",
            "5",
        ]
    )
    assert ns.command == SUBCOMMAND_STREAM
    assert ns.max_events == 10
    assert ns.max_duration == 3600.0
    assert ns.retail_max_events == 5


def test_parse_stream_rejects_rolling_flags() -> None:
    with pytest.raises(SystemExit):
        parse_args([SUBCOMMAND_STREAM, "-n", "5"])


def test_parse_stream_no_retail_without_calendar_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args([SUBCOMMAND_STREAM, "--no-retail"])


def test_stream_invalid_calendar_stderr_like_generate_events(tmp_path: Path) -> None:
    bad = tmp_path / "missing.json"
    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "stream",
            "--calendar",
            str(bad),
            "--seed",
            "1",
            "--retail-max-events",
            "1",
            "--max-events",
            "1",
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "fan_events:" in (p.stderr or "")

    p2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
            "-c",
            str(bad),
            "-o",
            str(tmp_path / "o.ndjson"),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    assert p2.returncode != 0
    assert "fan_events:" in (p2.stderr or "")


def test_stream_merged_writes_ndjson_lines(tmp_path: Path) -> None:
    out = tmp_path / "mixed.ndjson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "stream",
            "--calendar",
            str(_FIX),
            "--seed",
            "42",
            "-o",
            str(out),
            "--retail-max-events",
            "20",
            "--max-events",
            "40",
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    text = out.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 40
    assert any("retail_purchase" in ln for ln in lines)
    assert any("ticket_scan" in ln or "merch_purchase" in ln for ln in lines)


def test_run_stream_retail_only_stdout_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--seed",
            "7",
            "--retail-max-events",
            "3",
            "--max-events",
            "3",
        ]
    )
    run_stream(ns)
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 3
