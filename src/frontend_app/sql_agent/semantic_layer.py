"""Load and render the machine-readable semantic layer for Text-to-SQL prompts.

The semantic layer is a YAML file that describes:
- Subjects (primary analytics entities) and their canonical mart tables.
- Metrics (name, column, aggregation, unit).
- Dimensions (filter/group-by fields) and the tables that carry them.
- Join paths safe for the llm_reader role.
- Layering rules (when to prefer marts vs event tables).
- Answer-style guidelines (units, rounding, caveats).

Environment variables
---------------------
SEMANTIC_LAYER_FILE
    Absolute or relative path to the YAML file.
    Default: ``semantic/semantic_layer.yml`` beside this module.
    If an explicit path is given but the file is missing, ``SemanticLayerError``
    is raised immediately.

SEMANTIC_CONTEXT_MAX_CHARS
    Maximum characters for the rendered semantic summary injected into prompts.
    ``0`` (default) means uncapped.  When the limit is exceeded, the text is
    truncated with a banner (never raises).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

_DEFAULT_SEMANTIC_FILE = Path(__file__).resolve().parent / "semantic" / "semantic_layer.yml"
_SUPPORTED_VERSIONS = frozenset({1})


class SemanticLayerError(ValueError):
    """Raised when the semantic layer file is invalid, malformed, or missing."""


def _env_trim(name: str) -> str:
    return os.environ.get(name, "").strip()


def _resolve_semantic_path() -> tuple[Path, bool]:
    """Return (path, explicit) where *explicit* is True if the user set the env var."""
    raw = _env_trim("SEMANTIC_LAYER_FILE")
    if raw:
        return Path(raw).expanduser().resolve(), True
    return _DEFAULT_SEMANTIC_FILE, False


def load_semantic_layer() -> dict[str, Any]:
    """Read and validate the semantic layer YAML.

    Returns an empty dict if the default file is simply absent (no env var set).
    Raises ``SemanticLayerError`` on:
    - An explicitly configured path that does not exist.
    - A file that is not valid YAML.
    - A file with an unsupported ``version``.
    """
    path, explicit = _resolve_semantic_path()

    if not path.is_file():
        if explicit:
            raise SemanticLayerError(f"SEMANTIC_LAYER_FILE points to a missing file: {path}")
        log.warning(
            "Semantic layer file not found at default path %s; "
            "semantic context will be empty. "
            "Set SEMANTIC_LAYER_FILE to suppress this warning or provide the file.",
            path,
        )
        return {}

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SemanticLayerError(f"Cannot read semantic layer file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise SemanticLayerError(f"Semantic layer file {path} is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise SemanticLayerError(
            f"Semantic layer file {path} must contain a YAML mapping at the top level."
        )

    version = data.get("version")
    if version not in _SUPPORTED_VERSIONS:
        raise SemanticLayerError(
            f"Semantic layer file {path} declares version={version!r}, "
            f"but only versions {sorted(_SUPPORTED_VERSIONS)} are supported."
        )

    return data


def _apply_max_chars(text: str, label: str) -> str:
    max_raw = _env_trim("SEMANTIC_CONTEXT_MAX_CHARS")
    if not max_raw or max_raw == "0":
        return text
    try:
        max_chars = int(max_raw)
    except ValueError as exc:
        raise ValueError(
            f"SEMANTIC_CONTEXT_MAX_CHARS must be a non-negative integer or 0; "
            f"got {max_raw!r}"
        ) from exc
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    banner = f"[{label} TRUNCATED: original {len(text)} chars, limit {max_chars}]\n"
    budget = max_chars - len(banner)
    if budget <= 0:
        return banner[:max_chars]
    return banner + text[:budget]


def build_sql_semantic_context(layer: dict[str, Any]) -> str:
    """Render a compact semantic summary for the SQL-generation prompt.

    Returns an empty string when *layer* is empty (graceful degradation).
    """
    if not layer:
        return ""

    lines: list[str] = []

    # Subjects
    subjects = layer.get("subjects") or []
    if subjects:
        lines.append("ANALYTICS SUBJECTS AND PREFERRED TABLES:")
        for s in subjects:
            name = s.get("name", "?")
            mart = s.get("primary_mart", "?")
            prefer_mart = (s.get("prefer_mart_when") or "").strip().replace("\n", " ")
            prefer_event = (s.get("prefer_event_tables_when") or "").strip().replace("\n", " ")
            lines.append(f"  Subject: {name} → primary mart: {mart}")
            if prefer_mart:
                lines.append(f"    Use mart when: {prefer_mart}")
            if prefer_event:
                lines.append(f"    Use event tables when: {prefer_event}")
        lines.append("")

    # Layering rules
    layering = layer.get("layering_rules") or []
    if layering:
        lines.append("LAYERING RULES:")
        for rule in layering:
            desc = (rule.get("description") or "").strip().replace("\n", " ")
            if desc:
                lines.append(f"  - {desc}")
        lines.append("")

    # Metrics
    metrics = layer.get("metrics") or []
    if metrics:
        lines.append("AVAILABLE METRICS (name → table.column, unit):")
        for m in metrics:
            mname = m.get("name", "?")
            table = m.get("table", "?")
            col = m.get("column", "?")
            unit = m.get("unit", "")
            desc = (m.get("description") or "").strip().replace("\n", " ")
            unit_str = f" [{unit}]" if unit else ""
            lines.append(f"  - {mname}: {table}.{col}{unit_str} — {desc}")
        lines.append("")

    # Join paths
    joins = layer.get("join_paths") or []
    if joins:
        lines.append("VALID JOIN PATHS (llm_reader-safe):")
        for j in joins:
            from_t = j.get("from_table", "?")
            to_t = j.get("to_table", "?")
            on = j.get("on", "")
            lines.append(f"  - {from_t} ↔ {to_t}  ON {on}")
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    return _apply_max_chars(text, "SEMANTIC CONTEXT")


def build_answer_semantic_context(layer: dict[str, Any]) -> str:
    """Render a compact answer-style section for the answer-generation prompt.

    Returns an empty string when *layer* is empty (graceful degradation).
    """
    if not layer:
        return ""

    answer_style = layer.get("answer_style") or {}
    rules = answer_style.get("rules") or []

    if not rules:
        return ""

    lines: list[str] = ["ANSWER GUIDELINES:"]
    for rule in rules:
        lines.append(f"  - {rule}")
    lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    return _apply_max_chars(text, "ANSWER GUIDELINES")
