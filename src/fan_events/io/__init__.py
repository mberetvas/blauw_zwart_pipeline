"""Provide canonical NDJSON formatting and stream-ordering helpers.

These modules validate generated records, serialize them deterministically, and
handle atomic file writes so downstream ingestion sees stable event ordering.
"""
