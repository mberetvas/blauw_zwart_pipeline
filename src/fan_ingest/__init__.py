"""Consume fan-event Kafka topics and persist them into Postgres.

The ``fan_ingest`` package contains the local Compose-stack ingestion runtime,
including message parsing, async database writes, and the worker lifecycle used
by the ``fan_ingest`` console script.
"""

__all__: list[str] = []
