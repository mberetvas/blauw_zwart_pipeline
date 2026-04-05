"""CLI: generate_retail subcommand (v3 retail)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fan_events.cli import main

_REPO = Path(__file__).resolve().parents[1]


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO / "src")
    # Help/banner output is UTF-8; avoid Windows console codepage failures in subprocess.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_generate_retail_help_lists_duration_and_max_events() -> None:
    p = subprocess.run(
        [sys.executable, "-m", "fan_events", "generate_retail", "--help"],
        cwd=_REPO,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert "--max-duration" in out
    assert "--max-events" in out


def test_generate_retail_rejects_calendar_flag() -> None:
    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_retail",
            "--calendar",
            "x.json",
            "-o",
            "out.ndjson",
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    err = p.stderr or ""
    assert "cannot be used with generate_retail" in err or "unrecognized arguments" in err


def test_generate_retail_rejects_count_flag() -> None:
    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_retail",
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
    err = p.stderr or ""
    assert "cannot be used with generate_retail" in err or "unrecognized arguments" in err


def test_generate_retail_file_smoke(tmp_path: Path) -> None:
    out = tmp_path / "r.ndjson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_retail",
            "--seed",
            "1",
            "--max-events",
            "5",
            "-o",
            str(out),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    lines = text.strip().split("\n")
    assert len(lines) == 5
    assert all(json.loads(x)["event"] == "retail_purchase" for x in lines)


def test_generate_retail_stream_inprocess(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "generate_retail",
            "--seed",
            "2",
            "--stream",
            "--max-events",
            "3",
        ]
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.strip().split("\n")
    assert len(lines) == 3
    ts = [json.loads(x)["timestamp"] for x in lines]
    assert ts == sorted(ts)


def test_v1_still_runs_after_retail_subcommand_exists(tmp_path: Path) -> None:
    out = tmp_path / "v1.ndjson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
            "--seed",
            "1",
            "-n",
            "3",
            "--days",
            "30",
            "-o",
            str(out),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    assert out.read_text(encoding="utf-8").strip()
