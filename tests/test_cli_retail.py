"""CLI: generate_retail subcommand (v3 retail)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fan_events.cli import main, parse_args

_REPO = Path(__file__).resolve().parents[1]


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO / "src")
    # Help/banner output is UTF-8; avoid Windows console codepage failures in subprocess.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_generate_retail_short_aliases_parse() -> None:
    ns = parse_args(["generate_retail", "-n", "10", "-s", "3", "-o", "x.ndjson"])
    assert ns.max_events == 10
    assert ns.seed == 3
    assert ns.output == "x.ndjson"


def test_generate_events_short_aliases_parse() -> None:
    ns = parse_args(["generate_events", "-c", "cal.json", "-s", "7", "-o", "out.ndjson"])
    assert ns.calendar == "cal.json"
    assert ns.seed == 7


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
    assert "-n" in out
    assert "-d" in out
    assert "-s" in out
    assert "-t" in out
    assert "--emit-wall-clock-min" in out
    assert "--unlimited" in out
    assert "-u" in out


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
            "--count",
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
            "-s",
            "2",
            "-t",
            "-n",
            "3",
        ]
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.strip().split("\n")
    assert len(lines) == 3
    ts = [json.loads(x)["timestamp"] for x in lines]
    assert ts == sorted(ts)


def test_generate_retail_stream_wall_clock_zero_delay(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "generate_retail",
            "--seed",
            "2",
            "--stream",
            "--max-events",
            "3",
            "--emit-wall-clock-min",
            "0",
            "--emit-wall-clock-max",
            "0",
        ]
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.strip().split("\n")
    assert len(lines) == 3
    assert all(json.loads(x)["event"] == "retail_purchase" for x in lines)


def test_unlimited_stream_without_emit_or_duration_exits_error() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "generate_retail",
                "--stream",
                "--unlimited",
                "--seed",
                "1",
            ]
        )


def test_unlimited_file_without_duration_exits_error() -> None:
    with pytest.raises(SystemExit):
        main(["generate_retail", "--unlimited", "-o", "out.ndjson"])


def test_unlimited_conflicts_with_max_events() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "generate_retail",
                "--unlimited",
                "--max-events",
                "10",
                "--max-duration",
                "100",
                "-o",
                "out.ndjson",
            ]
        )


def test_unlimited_stream_with_max_duration_no_wall_clock(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(
        [
            "generate_retail",
            "--stream",
            "--unlimited",
            "--max-duration",
            "500",
            "--seed",
            "1",
            "--arrival-mode",
            "fixed",
            "--fixed-gap-seconds",
            "1",
        ]
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = [x for x in captured.out.strip().split("\n") if x.strip()]
    assert len(lines) > 200


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


def test_generate_retail_fans_out_parse() -> None:
    ns = parse_args(["generate_retail", "-F", "fans.json", "-n", "5", "-s", "1", "-o", "x.ndjson"])
    assert ns.fans_out == "fans.json"


def test_generate_retail_sidecar_bytes_identical_twice(tmp_path: Path) -> None:
    out1 = tmp_path / "r1.ndjson"
    out2 = tmp_path / "r2.ndjson"
    f1 = tmp_path / "f1.json"
    f2 = tmp_path / "f2.json"
    base = [
        sys.executable,
        "-m",
        "fan_events",
        "generate_retail",
        "-s",
        "42",
        "-n",
        "25",
        "-F",
    ]
    subprocess.run(
        base + [str(f1), "-o", str(out1)],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    subprocess.run(
        base + [str(f2), "-o", str(out2)],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")
    assert f1.read_text(encoding="utf-8") == f2.read_text(encoding="utf-8")


def test_generate_retail_events_unchanged_with_fans_out(tmp_path: Path) -> None:
    out_a = tmp_path / "a.ndjson"
    out_b = tmp_path / "b.ndjson"
    fans = tmp_path / "fans.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_retail",
            "-s",
            "7",
            "-n",
            "30",
            "-o",
            str(out_a),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_retail",
            "-s",
            "7",
            "-n",
            "30",
            "-o",
            str(out_b),
            "-F",
            str(fans),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    assert out_a.read_text(encoding="utf-8") == out_b.read_text(encoding="utf-8")
    doc = json.loads(fans.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert doc["rng_seed"] == 7
    raw = out_a.read_text(encoding="utf-8").strip().split("\n")
    ids_events = {json.loads(line)["fan_id"] for line in raw}
    assert set(doc["fans"]) == ids_events


def test_generate_retail_max_events_zero_sidecar_empty_fans(tmp_path: Path) -> None:
    out = tmp_path / "empty.ndjson"
    fans = tmp_path / "fans.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_retail",
            "-s",
            "1",
            "-n",
            "0",
            "-o",
            str(out),
            "-F",
            str(fans),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    assert out.read_bytes() == b""
    doc = json.loads(fans.read_text(encoding="utf-8"))
    assert doc["fans"] == {}
    assert doc["rng_seed"] == 1


def test_generate_retail_help_lists_fans_out() -> None:
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
    assert "--fans-out" in out
    assert "-F" in out


def test_generate_events_v2_calendar_fans_sidecar_keys_match_events(tmp_path: Path) -> None:
    cal = _REPO / "tests" / "fixtures" / "calendar_two_tiny.json"
    out = tmp_path / "v2.ndjson"
    fans = tmp_path / "fans2.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
            "-c",
            str(cal),
            "-s",
            "3",
            "-o",
            str(out),
            "-F",
            str(fans),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    raw = out.read_text(encoding="utf-8").strip().split("\n")
    lines = [x for x in raw if x]
    ids_events = {json.loads(line)["fan_id"] for line in lines}
    doc = json.loads(fans.read_text(encoding="utf-8"))
    assert set(doc["fans"]) == ids_events


def test_generate_events_v1_fans_sidecar_keys_match_events(tmp_path: Path) -> None:
    out = tmp_path / "ev.ndjson"
    fans = tmp_path / "fans.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fan_events",
            "generate_events",
            "-s",
            "2",
            "-n",
            "15",
            "-d",
            "40",
            "-o",
            str(out),
            "-F",
            str(fans),
        ],
        cwd=_REPO,
        env=_subprocess_env(),
        check=True,
    )
    lines = [x for x in out.read_text(encoding="utf-8").strip().split("\n") if x]
    ids_events = {json.loads(line)["fan_id"] for line in lines}
    doc = json.loads(fans.read_text(encoding="utf-8"))
    assert set(doc["fans"]) == ids_events
    assert doc["rng_seed"] == 2
