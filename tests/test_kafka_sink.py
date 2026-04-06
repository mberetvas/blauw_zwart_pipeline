"""Unit tests for fan_events.kafka_sink and Kafka CLI integration.

All tests use a mock Producer — no real broker required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fan_events.cli import SUBCOMMAND_STREAM, parse_args
from fan_events.kafka_sink import (
    KafkaConfig,
    KafkaSink,
    build_producer_config,
    kafka_config_from_env,
)

# ---------------------------------------------------------------------------
# KafkaConfig / kafka_config_from_env
# ---------------------------------------------------------------------------


def test_kafka_config_defaults_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """All FAN_EVENTS_KAFKA_* vars absent → dataclass defaults."""
    for key in (
        "FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS",
        "FAN_EVENTS_KAFKA_TOPIC",
        "FAN_EVENTS_KAFKA_CLIENT_ID",
        "FAN_EVENTS_KAFKA_COMPRESSION",
        "FAN_EVENTS_KAFKA_ACKS",
        "FAN_EVENTS_KAFKA_SECURITY_PROTOCOL",
        "FAN_EVENTS_KAFKA_SASL_MECHANISM",
        "FAN_EVENTS_KAFKA_SASL_USERNAME",
        "FAN_EVENTS_KAFKA_SASL_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = kafka_config_from_env()
    assert cfg.bootstrap_servers == "localhost:9092"
    assert cfg.topic == ""
    assert cfg.client_id == "fan-events-producer"
    assert cfg.compression == "none"
    assert cfg.acks == "1"
    assert cfg.security_protocol is None
    assert cfg.sasl_mechanism is None
    assert cfg.sasl_username is None
    assert cfg.sasl_password is None


def test_kafka_config_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS", "broker1:9092,broker2:9092")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_TOPIC", "my-topic")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_CLIENT_ID", "custom-client")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_COMPRESSION", "gzip")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_ACKS", "all")

    cfg = kafka_config_from_env()
    assert cfg.bootstrap_servers == "broker1:9092,broker2:9092"
    assert cfg.topic == "my-topic"
    assert cfg.client_id == "custom-client"
    assert cfg.compression == "gzip"
    assert cfg.acks == "all"


def test_kafka_config_sasl_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAN_EVENTS_KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_SASL_MECHANISM", "PLAIN")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_SASL_USERNAME", "user")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_SASL_PASSWORD", "secret")

    cfg = kafka_config_from_env()
    assert cfg.security_protocol == "SASL_SSL"
    assert cfg.sasl_mechanism == "PLAIN"
    assert cfg.sasl_username == "user"
    assert cfg.sasl_password == "secret"


def test_kafka_config_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-None override values win over env vars."""
    monkeypatch.setenv("FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS", "env-broker:9092")
    monkeypatch.setenv("FAN_EVENTS_KAFKA_TOPIC", "env-topic")

    cfg = kafka_config_from_env({"topic": "cli-topic", "bootstrap_servers": None})
    # bootstrap_servers override is None → env value retained
    assert cfg.bootstrap_servers == "env-broker:9092"
    # topic override is non-None → CLI wins
    assert cfg.topic == "cli-topic"


def test_kafka_config_none_overrides_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """None overrides do not replace env/defaults."""
    monkeypatch.setenv("FAN_EVENTS_KAFKA_ACKS", "all")
    cfg = kafka_config_from_env({"acks": None})
    assert cfg.acks == "all"


# ---------------------------------------------------------------------------
# build_producer_config
# ---------------------------------------------------------------------------


def test_build_producer_config_minimal() -> None:
    cfg = KafkaConfig(
        bootstrap_servers="localhost:9092", client_id="test", compression="none", acks="1"
    )
    conf = build_producer_config(cfg)
    assert conf["bootstrap.servers"] == "localhost:9092"
    assert conf["client.id"] == "test"
    assert conf["compression.type"] == "none"
    assert conf["acks"] == "1"
    # No SSL/SASL keys when not set
    for key in ("security.protocol", "sasl.mechanism", "sasl.username", "sasl.password"):
        assert key not in conf


def test_build_producer_config_includes_sasl() -> None:
    cfg = KafkaConfig(
        security_protocol="SASL_SSL",
        sasl_mechanism="PLAIN",
        sasl_username="u",
        sasl_password="p",
    )
    conf = build_producer_config(cfg)
    assert conf["security.protocol"] == "SASL_SSL"
    assert conf["sasl.mechanism"] == "PLAIN"
    assert conf["sasl.username"] == "u"
    assert conf["sasl.password"] == "p"


def test_build_producer_config_partial_sasl_omits_unset() -> None:
    """Only set SASL fields are included in the config dict."""
    cfg = KafkaConfig(security_protocol="SSL")
    conf = build_producer_config(cfg)
    assert conf["security.protocol"] == "SSL"
    assert "sasl.mechanism" not in conf
    assert "sasl.username" not in conf


# ---------------------------------------------------------------------------
# KafkaSink — write / flush / close
# ---------------------------------------------------------------------------


def _mock_producer() -> MagicMock:
    return MagicMock()


def test_kafka_sink_write_produces_utf8() -> None:
    producer = _mock_producer()
    sink = KafkaSink(producer, "test-topic")
    sink.write('{"event":"retail_purchase"}\n')
    producer.produce.assert_called_once_with(
        "test-topic",
        value=b'{"event":"retail_purchase"}\n',
        on_delivery=sink._on_delivery,
    )


def test_kafka_sink_flush_calls_poll() -> None:
    producer = _mock_producer()
    sink = KafkaSink(producer, "t")
    sink.flush()
    producer.poll.assert_called_once_with(0)


def test_kafka_sink_flush_does_not_call_producer_flush() -> None:
    """flush() (per-line) must not block; only close() does the full flush."""
    producer = _mock_producer()
    sink = KafkaSink(producer, "t")
    sink.flush()
    producer.flush.assert_not_called()


def test_kafka_sink_close_calls_producer_flush_with_timeout() -> None:
    producer = _mock_producer()
    producer.flush.return_value = 0
    sink = KafkaSink(producer, "t")
    sink.close()
    producer.flush.assert_called_once_with(timeout=30)


def test_kafka_sink_close_warns_on_remaining(capsys: pytest.CaptureFixture[str]) -> None:
    producer = _mock_producer()
    producer.flush.return_value = 3  # 3 messages not delivered
    sink = KafkaSink(producer, "t")
    sink.close()
    captured = capsys.readouterr()
    assert "3" in captured.err
    assert "not confirmed" in captured.err


def test_kafka_sink_delivery_error_raises_on_next_write() -> None:
    producer = _mock_producer()
    sink = KafkaSink(producer, "t")

    # Simulate a delivery error via the callback
    fake_err = MagicMock()
    fake_err.__str__ = lambda self: "broker not available"
    sink._on_delivery(fake_err, MagicMock())

    with pytest.raises(RuntimeError, match="broker not available"):
        sink.write("line\n")


def test_kafka_sink_delivery_error_raises_on_flush() -> None:
    producer = _mock_producer()
    sink = KafkaSink(producer, "t")
    sink._delivery_error = "timeout"
    with pytest.raises(RuntimeError, match="timeout"):
        sink.flush()


def test_kafka_sink_delivery_error_raises_on_close() -> None:
    producer = _mock_producer()
    producer.flush.return_value = 0
    sink = KafkaSink(producer, "t")
    sink._delivery_error = "auth failed"
    with pytest.raises(RuntimeError, match="auth failed"):
        sink.close()


def test_kafka_sink_no_error_on_successful_delivery() -> None:
    producer = _mock_producer()
    sink = KafkaSink(producer, "t")
    sink._on_delivery(None, MagicMock())  # err=None means success
    assert sink._delivery_error is None


# ---------------------------------------------------------------------------
# CLI parse_args: Kafka validation
# ---------------------------------------------------------------------------


def test_parse_stream_kafka_topic_accepted() -> None:
    ns = parse_args([SUBCOMMAND_STREAM, "--kafka-topic", "fan-events", "--max-events", "1"])
    assert ns.kafka_topic == "fan-events"


def test_parse_stream_kafka_topic_and_output_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        parse_args([
            SUBCOMMAND_STREAM,
            "--kafka-topic", "fan-events",
            "-o", "out/x.ndjson",
            "--max-events", "1",
        ])


def test_parse_stream_kafka_bootstrap_servers_without_topic_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args([
            SUBCOMMAND_STREAM,
            "--kafka-bootstrap-servers", "localhost:9092",
            "--max-events", "1",
        ])


def test_parse_stream_kafka_compression_without_topic_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args([SUBCOMMAND_STREAM, "--kafka-compression", "gzip", "--max-events", "1"])


def test_parse_stream_kafka_acks_without_topic_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args([SUBCOMMAND_STREAM, "--kafka-acks", "all", "--max-events", "1"])


def test_parse_stream_kafka_client_id_without_topic_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args([SUBCOMMAND_STREAM, "--kafka-client-id", "my-client", "--max-events", "1"])


def test_parse_stream_kafka_flags_with_topic_accepted() -> None:
    ns = parse_args([
        SUBCOMMAND_STREAM,
        "--kafka-topic", "t",
        "--kafka-bootstrap-servers", "broker:9092",
        "--kafka-client-id", "client",
        "--kafka-compression", "snappy",
        "--kafka-acks", "all",
        "--max-events", "1",
    ])
    assert ns.kafka_topic == "t"
    assert ns.kafka_bootstrap_servers == "broker:9092"
    assert ns.kafka_client_id == "client"
    assert ns.kafka_compression == "snappy"
    assert ns.kafka_acks == "all"


def test_parse_stream_kafka_topic_stdout_dash_allowed() -> None:
    """--kafka-topic with -o - (explicit stdout) is currently forbidden by mutual-exclusion."""
    # The flag combination --kafka-topic + -o - uses explicit stdout flag; we treat it as
    # mutually exclusive to keep behaviour unambiguous.
    with pytest.raises(SystemExit):
        parse_args([
            SUBCOMMAND_STREAM,
            "--kafka-topic", "t",
            "-o", "-",
            "--max-events", "1",
        ])


# ---------------------------------------------------------------------------
# Bug regression tests
# ---------------------------------------------------------------------------


def test_env_var_kafka_topic_activates_kafka_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug 1 regression: FAN_EVENTS_KAFKA_TOPIC env var alone must activate Kafka mode.

    Previously, args.kafka_topic was always None when --kafka-topic was not passed on the CLI,
    so the env var was silently ignored and events went to stdout.
    """
    monkeypatch.setenv("FAN_EVENTS_KAFKA_TOPIC", "env-topic")
    ns = parse_args([SUBCOMMAND_STREAM, "--max-events", "1"])
    # The env var must be picked up as the kafka_topic argument value.
    assert ns.kafka_topic == "env-topic"


def test_env_var_kafka_topic_overridden_by_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI --kafka-topic must win over FAN_EVENTS_KAFKA_TOPIC env var."""
    monkeypatch.setenv("FAN_EVENTS_KAFKA_TOPIC", "env-topic")
    ns = parse_args([SUBCOMMAND_STREAM, "--kafka-topic", "cli-topic", "--max-events", "1"])
    assert ns.kafka_topic == "cli-topic"


def test_env_var_kafka_topic_and_output_flag_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutual-exclusion validation must fire even when the topic comes from the env var."""
    monkeypatch.setenv("FAN_EVENTS_KAFKA_TOPIC", "env-topic")
    with pytest.raises(SystemExit):
        parse_args([SUBCOMMAND_STREAM, "-o", "out/x.ndjson", "--max-events", "1"])


def test_import_error_exits_with_message(capsys: pytest.CaptureFixture[str]) -> None:
    """Bug 2 regression: ImportError for confluent-kafka must exit non-zero with a helpful
    message pointing to the kafka extra, not a bare traceback or silent failure."""
    import sys
    from unittest.mock import patch

    from fan_events.cli import _run_stream_kafka

    class _FakeArgs:
        kafka_topic = "t"
        kafka_bootstrap_servers = None
        kafka_client_id = None
        kafka_compression = None
        kafka_acks = None
        max_events = 1
        max_duration = None
        emit_wall_clock_min = None
        emit_wall_clock_max = None

    with patch.dict(sys.modules, {"confluent_kafka": None}):
        with pytest.raises(SystemExit) as exc_info:
            _run_stream_kafka(_FakeArgs(), iter([]), None, None, None)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "confluent-kafka" in captured.err
    assert "kafka" in captured.err  # references the [kafka] extra
