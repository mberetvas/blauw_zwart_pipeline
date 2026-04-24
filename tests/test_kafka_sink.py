"""Unit tests for fan_events.kafka_sink and Kafka CLI integration.

All tests use a mock Producer — no real broker required.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from fan_events.cli import SUBCOMMAND_STREAM, parse_args
from fan_events.sinks.kafka_sink import (
    KafkaConfig,
    KafkaSink,
    build_producer_config,
    kafka_config_from_env,
    summarize_bootstrap_for_log,
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


@pytest.fixture(autouse=True)
def _reset_kafka_logger() -> None:
    """Ensure the fan_events.kafka logger is clean between tests."""
    kafka_logger = logging.getLogger("fan_events.kafka")
    kafka_logger.handlers.clear()
    kafka_logger.setLevel(logging.NOTSET)


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


def test_kafka_sink_close_warns_on_remaining(caplog: pytest.LogCaptureFixture) -> None:
    producer = _mock_producer()
    producer.flush.return_value = 3  # 3 messages not delivered
    sink = KafkaSink(producer, "t")
    with caplog.at_level(logging.WARNING, logger="fan_events.kafka"):
        sink.close()
    assert any("3" in r.message and "not confirmed" in r.message for r in caplog.records)


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
        verbose = False

    with patch.dict(sys.modules, {"confluent_kafka": None}):
        with pytest.raises(SystemExit) as exc_info:
            _run_stream_kafka(_FakeArgs(), iter([]), None, None, None)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "confluent-kafka" in captured.err
    assert "kafka" in captured.err  # references the [kafka] extra


# ---------------------------------------------------------------------------
# summarize_bootstrap_for_log
# ---------------------------------------------------------------------------


def test_summarize_bootstrap_single_broker() -> None:
    assert summarize_bootstrap_for_log("localhost:9092") == "1 broker (localhost:9092)"


def test_summarize_bootstrap_multiple_brokers() -> None:
    result = summarize_bootstrap_for_log("broker1:9092, broker2:9092, broker3:9092")
    assert "3 brokers" in result
    assert "broker1:9092" in result


def test_summarize_bootstrap_empty_string() -> None:
    assert summarize_bootstrap_for_log("") == "0 brokers"


# ---------------------------------------------------------------------------
# KafkaSink — logging (progress, delivery errors, close)
# ---------------------------------------------------------------------------


def test_kafka_sink_progress_log_at_interval(caplog: pytest.LogCaptureFixture) -> None:
    """After *progress_interval* successful deliveries an INFO log should appear."""
    producer = _mock_producer()
    sink = KafkaSink(producer, "t", progress_interval=4)

    mock_msg = MagicMock()
    mock_msg.value.return_value = b"payload"

    with caplog.at_level(logging.INFO, logger="fan_events.kafka"):
        for _ in range(4):
            sink._on_delivery(None, mock_msg)

    progress_records = [r for r in caplog.records if "produced 4 messages" in r.message]
    assert len(progress_records) == 1


def test_kafka_sink_no_progress_log_before_interval(caplog: pytest.LogCaptureFixture) -> None:
    """Before reaching progress_interval, no INFO progress log should appear."""
    producer = _mock_producer()
    sink = KafkaSink(producer, "t", progress_interval=256)

    mock_msg = MagicMock()
    mock_msg.value.return_value = b"x"

    with caplog.at_level(logging.INFO, logger="fan_events.kafka"):
        for _ in range(10):
            sink._on_delivery(None, mock_msg)

    progress_records = [r for r in caplog.records if "produced" in r.message]
    assert len(progress_records) == 0


def test_kafka_sink_delivery_error_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Delivery failure must emit an ERROR log with the broker error string."""
    producer = _mock_producer()
    sink = KafkaSink(producer, "t")

    fake_err = MagicMock()
    fake_err.__str__ = lambda self: "broker not available"

    with caplog.at_level(logging.ERROR, logger="fan_events.kafka"):
        sink._on_delivery(fake_err, MagicMock())

    assert any(
        r.levelno == logging.ERROR and "broker not available" in r.message for r in caplog.records
    )
    # Still stores the error for RuntimeError on next operation
    assert sink._delivery_error == "broker not available"


def test_kafka_sink_close_info_log(caplog: pytest.LogCaptureFixture) -> None:
    """close() must emit an INFO log about flushing."""
    producer = _mock_producer()
    producer.flush.return_value = 0
    sink = KafkaSink(producer, "t")
    with caplog.at_level(logging.INFO, logger="fan_events.kafka"):
        sink.close()
    assert any("flushing" in r.message.lower() for r in caplog.records)


def test_kafka_sink_counters_accumulate() -> None:
    """produced_count and produced_bytes accumulate across deliveries."""
    producer = _mock_producer()
    sink = KafkaSink(producer, "t")

    msg = MagicMock()
    msg.value.return_value = b"hello"

    for _ in range(5):
        sink._on_delivery(None, msg)

    assert sink._produced_count == 5
    assert sink._produced_bytes == 25


# ---------------------------------------------------------------------------
# CLI: --verbose flag
# ---------------------------------------------------------------------------


def test_parse_stream_verbose_flag() -> None:
    ns = parse_args([SUBCOMMAND_STREAM, "--verbose", "--kafka-topic", "t", "--max-events", "1"])
    assert ns.verbose is True


def test_parse_stream_no_verbose_default() -> None:
    ns = parse_args([SUBCOMMAND_STREAM, "--kafka-topic", "t", "--max-events", "1"])
    assert ns.verbose is False


# ---------------------------------------------------------------------------
# CLI integration: _run_stream_kafka startup log
# ---------------------------------------------------------------------------


def test_run_stream_kafka_startup_log(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_stream_kafka must emit an INFO startup line with topic and bootstrap summary."""
    import sys
    from unittest.mock import patch

    from fan_events.cli import _run_stream_kafka

    class _FakeArgs:
        kafka_topic = "test-topic"
        kafka_bootstrap_servers = "broker1:9092,broker2:9092"
        kafka_client_id = "test-client"
        kafka_compression = None
        kafka_acks = None
        max_events = 0
        max_duration = None
        emit_wall_clock_min = None
        emit_wall_clock_max = None
        verbose = False

    mock_producer_cls = MagicMock()
    mock_producer_instance = MagicMock()
    mock_producer_instance.flush.return_value = 0
    mock_producer_cls.return_value = mock_producer_instance

    kafka_logger = logging.getLogger("fan_events.kafka")
    kafka_logger.addHandler(caplog.handler)

    with (
        caplog.at_level(logging.INFO, logger="fan_events.kafka"),
        patch.dict(sys.modules, {"confluent_kafka": MagicMock(Producer=mock_producer_cls)}),
    ):
        _run_stream_kafka(_FakeArgs(), iter([]), None, None, None)

    startup = [r for r in caplog.records if "test-topic" in r.message]
    assert len(startup) >= 1
    assert any("2 brokers" in r.message for r in startup)
    # Must NOT contain SASL passwords
    assert not any(
        "sasl" in r.message.lower() and "password" in r.message.lower()
        for r in caplog.records
    )
