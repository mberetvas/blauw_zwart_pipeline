"""Generate and stream synthetic Club Brugge fan activity datasets.

The package groups rolling-window, match-calendar, and retail generation flows
plus serialization and sink helpers used by the ``fan_events`` CLI. Runtime
side effects such as file writes and Kafka publishing live in dedicated
subpackages so generation logic stays reviewable and testable.
"""
