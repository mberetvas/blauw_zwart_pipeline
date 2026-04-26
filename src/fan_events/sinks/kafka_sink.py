"""Kafka sink for the ``fan_events stream`` subcommand.

Configuration is read from ``FAN_EVENTS_KAFKA_*`` environment variables; CLI flags passed as
*overrides* take precedence when both are set.

Environment variables
---------------------
FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS   Comma-separated broker list (default: localhost:9092)
FAN_EVENTS_KAFKA_TOPIC               Target topic name (required when Kafka mode is active)
FAN_EVENTS_KAFKA_CLIENT_ID           Producer client.id (default: fan-events-producer)
FAN_EVENTS_KAFKA_COMPRESSION         Compression codec: none|gzip|snappy|lz4|zstd (default: none)
FAN_EVENTS_KAFKA_ACKS                Required acks: 0|1|all|-1 (default: 1)

For TLS/SASL (env only — keep secrets out of shell history):
FAN_EVENTS_KAFKA_SECURITY_PROTOCOL   e.g. SASL_SSL
FAN_EVENTS_KAFKA_SASL_MECHANISM      e.g. PLAIN, SCRAM-SHA-256
FAN_EVENTS_KAFKA_SASL_USERNAME       SASL username
FAN_EVENTS_KAFKA_SASL_PASSWORD       SASL password

Progress logging (optional)
---------------------------
Set ``FAN_EVENTS_KAFKA_PROGRESS_INTERVAL`` to a positive integer to log a summary every *N*
successful deliveries (default **256** when unset). Use ``0`` to disable progress INFO lines.
CLI/tests may pass ``progress_interval=…`` to :class:`KafkaSink` explicitly; that overrides
the env var.

Message key
-----------
All messages are produced with ``key=None`` (null → Kafka round-robin partitioning).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fan_events.kafka")

_ENV_PREFIX = "FAN_EVENTS_KAFKA_"


@dataclass
class KafkaConfig:
    """Configuration for publishing the merged stream to Kafka.

    Attributes:
        bootstrap_servers: Comma-separated Kafka broker list.
        topic: Destination topic name.
        client_id: Producer client identifier.
        compression: Compression codec understood by Kafka.
        acks: Required broker acknowledgements.
        security_protocol: Optional security protocol such as ``SASL_SSL``.
        sasl_mechanism: Optional SASL mechanism name.
        sasl_username: Optional SASL username.
        sasl_password: Optional SASL password.
        _extra: Reserved passthrough settings for future producer options.
    """

    bootstrap_servers: str = "localhost:9092"
    topic: str = ""
    client_id: str = "fan-events-producer"
    compression: str = "none"
    acks: str = "1"
    # SSL / SASL — env-only, no CLI flags (keep secrets out of shell history)
    security_protocol: str | None = None
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None
    # Extra raw confluent-kafka producer config (unused by default; reserved for future use)
    _extra: dict[str, str] = field(default_factory=dict, repr=False)


def kafka_config_from_env(overrides: dict[str, str | None] | None = None) -> KafkaConfig:
    """Build Kafka configuration from environment variables and CLI overrides.

    Args:
        overrides: Optional mapping of explicit override values. Only non-``None``
            values replace environment-derived defaults.

    Returns:
        Kafka configuration ready to convert into producer settings.
    """
    cfg = KafkaConfig(
        bootstrap_servers=os.environ.get(f"{_ENV_PREFIX}BOOTSTRAP_SERVERS", "localhost:9092"),
        topic=os.environ.get(f"{_ENV_PREFIX}TOPIC", ""),
        client_id=os.environ.get(f"{_ENV_PREFIX}CLIENT_ID", "fan-events-producer"),
        compression=os.environ.get(f"{_ENV_PREFIX}COMPRESSION", "none"),
        acks=os.environ.get(f"{_ENV_PREFIX}ACKS", "1"),
        security_protocol=os.environ.get(f"{_ENV_PREFIX}SECURITY_PROTOCOL"),
        sasl_mechanism=os.environ.get(f"{_ENV_PREFIX}SASL_MECHANISM"),
        sasl_username=os.environ.get(f"{_ENV_PREFIX}SASL_USERNAME"),
        sasl_password=os.environ.get(f"{_ENV_PREFIX}SASL_PASSWORD"),
    )
    if overrides:
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
    return cfg


def build_producer_config(cfg: KafkaConfig) -> dict[str, Any]:
    """Translate :class:`KafkaConfig` into ``confluent_kafka`` settings.

    Args:
        cfg: High-level Kafka configuration.

    Returns:
        Producer configuration dictionary suitable for ``Producer(...)``.
    """
    conf: dict[str, Any] = {
        "bootstrap.servers": cfg.bootstrap_servers,
        "client.id": cfg.client_id,
        "compression.type": cfg.compression,
        "acks": cfg.acks,
    }
    if cfg.security_protocol:
        conf["security.protocol"] = cfg.security_protocol
    if cfg.sasl_mechanism:
        conf["sasl.mechanism"] = cfg.sasl_mechanism
    if cfg.sasl_username:
        conf["sasl.username"] = cfg.sasl_username
    if cfg.sasl_password:
        conf["sasl.password"] = cfg.sasl_password
    conf.update(cfg._extra)
    return conf


def summarize_bootstrap_for_log(servers: str) -> str:
    """Return a concise, credential-safe bootstrap summary for INFO logs.

    Args:
        servers: Raw comma-separated broker list.

    Returns:
        Human-readable broker summary suitable for INFO-level logs.
    """
    brokers = [b.strip() for b in servers.split(",") if b.strip()]
    count = len(brokers)
    if count == 0:
        return "0 brokers"
    if count == 1:
        return f"1 broker ({brokers[0]})"
    return f"{count} brokers (first: {brokers[0]})"


class KafkaSink:
    """Duck-typed sink that publishes NDJSON lines to a Kafka topic.

    Designed to be passed to
    :func:`fan_events.generation.orchestrator.write_merged_stream` in place of a
    :class:`io.TextIO` object.  Implements ``.write()`` and ``.flush()`` to match the interface
    used by ``write_merged_stream``, plus ``.close()`` for clean shutdown.

    Lifecycle::

        sink = KafkaSink(producer, topic)
        try:
            write_merged_stream(merged, sink, ...)
        finally:
            sink.close()   # blocks until all in-flight messages are delivered

    Flush semantics
    ---------------
    - ``flush()``  — calls ``producer.poll(0)`` to drain delivery callbacks without blocking;
      called after every line by ``write_merged_stream``.
    - ``close()``  — calls ``producer.flush(timeout=30)`` to block until delivery; call once on
      shutdown (normal completion *or* Ctrl+C via ``try/finally``).

    Error handling
    --------------
    Delivery failures are captured via a per-message callback.  The first error is stored and
    re-raised as :class:`RuntimeError` on the next ``.write()``, ``.flush()``, or ``.close()``
    call.
    """

    def __init__(
        self,
        producer: Any,
        topic: str,
        *,
        progress_interval: int | None = None,
    ) -> None:
        """Initialize a Kafka-backed sink compatible with ``write_merged_stream``.

        Args:
            producer: ``confluent_kafka.Producer``-compatible instance.
            topic: Destination topic name.
            progress_interval: Optional number of successful deliveries between
                progress log lines. ``None`` falls back to the environment.
        """
        self._producer = producer
        self._topic = topic
        self._delivery_error: str | None = None
        if progress_interval is not None:
            self._progress_interval = max(0, progress_interval)
        else:
            raw = os.environ.get("FAN_EVENTS_KAFKA_PROGRESS_INTERVAL", "").strip()
            if raw == "":
                self._progress_interval = 256
            else:
                try:
                    self._progress_interval = max(0, int(raw))
                except ValueError:
                    self._progress_interval = 256
        # Delivery counters are maintained here so progress logs stay sink-local
        # even when multiple sinks exist in the same process.
        self._produced_count: int = 0
        self._produced_bytes: int = 0

    def _on_delivery(self, err: Any, _msg: Any) -> None:
        """Handle one asynchronous Kafka delivery callback."""
        if err is not None:
            logger.error("Kafka delivery failed: %s", err)
            if self._delivery_error is None:
                self._delivery_error = str(err)
            return
        self._produced_count += 1
        if _msg is not None:
            try:
                self._produced_bytes += len(_msg.value()) if _msg.value() else 0
            except Exception:  # noqa: BLE001 – defensive; mock messages may not support .value()
                pass
        if self._progress_interval > 0 and self._produced_count % self._progress_interval == 0:
            logger.info(
                "Kafka: produced %d messages (~%d bytes)",
                self._produced_count,
                self._produced_bytes,
            )

    def _check_error(self) -> None:
        """Raise the first stored delivery error, if any."""
        if self._delivery_error:
            raise RuntimeError(f"Kafka delivery error: {self._delivery_error}")

    def write(self, line: str) -> None:
        """Publish one NDJSON line to Kafka.

        Args:
            line: LF-terminated NDJSON line produced by the stream orchestrator.

        Raises:
            RuntimeError: If a prior asynchronous delivery callback already
                reported a Kafka error.
        """
        self._check_error()
        logger.debug(
            "task=kafka_produce previous=line_ready next=delivery_callback topic=%s bytes=%d",
            self._topic,
            len(line.encode("utf-8")),
        )
        self._producer.produce(
            self._topic,
            value=line.encode("utf-8"),
            on_delivery=self._on_delivery,
        )

    def flush(self) -> None:
        """Poll for Kafka delivery callbacks without blocking.

        Raises:
            RuntimeError: If any prior delivery callback captured an error.
        """
        self._producer.poll(0)
        self._check_error()

    def close(self) -> None:
        """Flush in-flight Kafka messages during sink shutdown.

        Raises:
            RuntimeError: If a prior delivery callback captured an error.
        """
        logger.info("Closing Kafka producer — flushing in-flight messages")
        remaining = self._producer.flush(timeout=30)
        if remaining > 0:
            logger.warning("%d Kafka message(s) not confirmed before flush timeout", remaining)
        self._check_error()
