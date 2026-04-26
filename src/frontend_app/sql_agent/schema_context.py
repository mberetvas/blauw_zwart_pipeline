"""Load and merge dbt schema YAML files for Text-to-SQL prompts.

This module discovers one or more dbt schema files, merges their model and
column descriptions, and renders a compact text block that can be injected into
prompt templates. It performs filesystem I/O only; callers receive plain text.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Default single-file path (same as historical app.py default).
_DEFAULT_SCHEMA_FILE = Path(__file__).resolve().parent / "schema.yml"


class SchemaContextOverflowError(ValueError):
    """Raised when rendered schema context exceeds the configured size budget."""


def _env_trim(name: str) -> str:
    """Return a stripped environment variable value, or ``""`` when unset."""
    return os.environ.get(name, "").strip()


def _layer_rank_and_label(path: Path) -> tuple[int, str]:
    """Infer a sort rank and human label from a dbt schema file path."""
    parts = {p.lower() for p in path.parts}
    if "staging" in parts:
        return 0, "staging"
    if "intermediate" in parts:
        return 1, "intermediate"
    if "marts" in parts:
        return 2, "marts"
    return 99, "unspecified"


def _parse_schema_files_list(raw: str) -> list[Path]:
    """Parse a comma-separated schema file list from the environment."""
    return [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()]


def _discover_dbt_models_dir(root: Path) -> list[Path]:
    """Discover schema YAML files beneath a dbt ``models`` directory."""
    if not root.is_dir():
        raise FileNotFoundError(f"DBT_MODELS_DIR is not a directory: {root}")

    files: list[Path] = []
    files.extend(sorted(root.rglob("*_schema.yaml")))
    marts_schema = root / "marts" / "schema.yml"
    if marts_schema.is_file():
        files.append(marts_schema)

    # De-duplicate (e.g. if a path matched twice) while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(f)

    keyed = []
    for f in unique:
        rank, _ = _layer_rank_and_label(f)
        if rank == 99:
            log.warning(
                "Schema file path has no staging/intermediate/marts segment; "
                "layer will be 'unspecified': %s",
                f,
            )
        keyed.append((rank, str(f.resolve()), f))

    keyed.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in keyed]


def _resolve_schema_paths() -> list[Path]:
    """Resolve schema file paths from ``SCHEMA_FILES``, ``DBT_MODELS_DIR``, or fallback."""
    files_raw = _env_trim("SCHEMA_FILES")
    if files_raw:
        return _parse_schema_files_list(files_raw)

    dbt_dir = _env_trim("DBT_MODELS_DIR")
    if dbt_dir:
        return _discover_dbt_models_dir(Path(dbt_dir).expanduser())

    single = _env_trim("SCHEMA_FILE")
    path = Path(single).expanduser() if single else _DEFAULT_SCHEMA_FILE
    return [path]


def _load_models_from_file(path: Path) -> list[dict[str, Any]]:
    """Load dbt ``models`` entries from one YAML schema file."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    out: list[dict[str, Any]] = []
    for m in models:
        if isinstance(m, dict) and m.get("name"):
            out.append(m)
    return out


def _format_model(model: dict[str, Any], layer_label: str) -> list[str]:
    """Render one dbt model entry as prompt-friendly text lines."""
    parts: list[str] = []
    parts.append(f"Layer: {layer_label}")
    parts.append(f"Table: {model['name']}")
    desc = (model.get("description") or "").strip().replace("\n", " ")
    if desc:
        parts.append(f"  Description: {desc}")
    for col in model.get("columns", []) or []:
        if not isinstance(col, dict) or not col.get("name"):
            continue
        col_desc = (col.get("description") or "").strip().replace("\n", " ")
        parts.append(f"  - {col['name']} ({col.get('data_type', '?')}): {col_desc}")
    parts.append("")
    return parts


def _apply_size_limit(text: str) -> str:
    """Apply the optional schema-context size limit configured via env vars."""
    max_raw = _env_trim("SCHEMA_CONTEXT_MAX_CHARS")
    if not max_raw or max_raw == "0":
        return text

    try:
        max_chars = int(max_raw)
    except ValueError as exc:
        raise ValueError(
            f"SCHEMA_CONTEXT_MAX_CHARS must be a non-negative integer or 0; "
            f"got {max_raw!r}"
        ) from exc
    if max_chars <= 0:
        return text

    mode = _env_trim("SCHEMA_CONTEXT_OVERFLOW").lower() or "error"
    if mode not in {"error", "truncate"}:
        raise ValueError(f"SCHEMA_CONTEXT_OVERFLOW must be 'error' or 'truncate'; got {mode!r}")

    if len(text) <= max_chars:
        return text

    if mode == "error":
        raise SchemaContextOverflowError(
            f"Schema context is {len(text)} characters; limit is {max_chars} "
            f"(SCHEMA_CONTEXT_MAX_CHARS). Raise the limit, set SCHEMA_CONTEXT_OVERFLOW=truncate, "
            "or reduce SCHEMA_FILES / DBT_MODELS_DIR content."
        )

    banner = (
        "[SCHEMA CONTEXT TRUNCATED] "
        f"Original length was {len(text)} characters; SCHEMA_CONTEXT_MAX_CHARS={max_chars}. "
        "Tail of the schema description was removed.\n\n"
    )
    budget = max_chars - len(banner)
    if budget <= 0:
        return banner[:max_chars]
    return banner + text[:budget]


def build_schema_context_text() -> str:
    """Read configured schema YAML file(s) and return prompt-friendly text.

    Returns:
        Human-readable schema summary describing tables, layers, and columns.

    Raises:
        FileNotFoundError: If an explicitly selected schema file is missing.
        SchemaContextOverflowError: If the rendered text exceeds the configured
            limit while overflow mode is ``error``.
        ValueError: If environment configuration is invalid.
    """
    paths = _resolve_schema_paths()
    relation_schema = _env_trim("DBT_RELATION_SCHEMA") or "dbt_dev"

    # model_name -> (model_dict, layer_rank, layer_label, source_path)
    merged: dict[str, tuple[dict[str, Any], int, str, Path]] = {}

    for path in paths:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Schema file not found: {path}")

        layer_rank, layer_label = _layer_rank_and_label(path)
        # Later files intentionally win so callers can override shared models by
        # ordering SCHEMA_FILES explicitly.
        for model in _load_models_from_file(path):
            name = str(model["name"])
            if name in merged:
                prev_path = merged[name][3]
                log.warning(
                    "Duplicate dbt model %r: %s overrides %s (later file wins)",
                    name,
                    path,
                    prev_path,
                )
            merged[name] = (model, layer_rank, layer_label, path)

    preamble = (
        f"PostgreSQL schema: {relation_schema} (default search_path for llm_reader). "
        f"Use unqualified relation names or qualify as {relation_schema}.<relation>.\n\n"
    )

    # Render models in layer order so staging context appears before marts.
    ordered_names = sorted(
        merged.keys(),
        key=lambda n: (merged[n][1], n),
    )

    body_parts: list[str] = []
    for name in ordered_names:
        model, _, layer_label, _ = merged[name]
        body_parts.extend(_format_model(model, layer_label))

    text = preamble + "\n".join(body_parts).rstrip() + "\n"
    return _apply_size_limit(text)
