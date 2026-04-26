"""Host output adapters for generated fan-event streams.

Sinks translate validated records into external side effects such as Kafka
publishes while keeping the core generators free of transport-specific code.
"""
