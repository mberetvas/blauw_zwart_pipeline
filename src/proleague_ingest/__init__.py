"""Ingest scraped Pro League player statistics from Kafka into Postgres.

The package contains the consumer loop and CLI entrypoint responsible for
turning ``player_stats`` topic messages into database upserts.
"""

__all__: list[str] = []
