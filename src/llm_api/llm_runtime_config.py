"""Runtime LLM settings: environment defaults, JSON file overlay, thread-safe updates.

Precedence
----------
1. On startup, values are loaded from environment variables (same names as before).
2. If ``LLM_CONFIG_PATH`` points to an existing JSON file, its keys overlay the env
   defaults (persisted settings win).
3. ``PUT /api/llm-config`` updates the in-memory state and rewrites that JSON file.

OpenRouter API keys are stored only in the JSON file or environment — never exposed
in full to clients (GET returns a masked suffix only).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_lock = threading.RLock()
_state: dict[str, Any] = {}
_CONFIG_PATH: Path | None = None

_MERGE_KEYS = frozenset(
    {
        "ollama_url",
        "ollama_model",
        "ollama_timeout",
        "openrouter_base_url",
        "openrouter_model",
        "openrouter_timeout",
        "openrouter_api_key",
        "default_provider",
    }
)

_STR_KEYS = frozenset(
    {
        "ollama_url",
        "ollama_model",
        "openrouter_base_url",
        "openrouter_model",
        "default_provider",
    }
)


def config_path() -> Path:
    """Resolved path to the persisted JSON file (default: beside this package)."""
    global _CONFIG_PATH
    if _CONFIG_PATH is None:
        raw = os.environ.get("LLM_CONFIG_PATH", "").strip()
        if raw:
            _CONFIG_PATH = Path(raw).expanduser().resolve()
        else:
            _CONFIG_PATH = (Path(__file__).resolve().parent / "llm_config.json")
    return _CONFIG_PATH


def _defaults_from_env() -> dict[str, Any]:
    return {
        "ollama_url": os.environ.get(
            "OLLAMA_URL", "http://host.docker.internal:11434"
        ).rstrip("/"),
        "ollama_model": os.environ.get("OLLAMA_MODEL", "gemma4:e2b").strip(),
        "ollama_timeout": int(os.environ.get("OLLAMA_TIMEOUT", "120")),
        "openrouter_base_url": os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        "openrouter_model": os.environ.get(
            "OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free"
        ).strip(),
        "openrouter_timeout": int(os.environ.get("OPENROUTER_TIMEOUT", "120")),
        "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", "").strip(),
        "default_provider": os.environ.get("LLM_PROVIDER", "ollama").strip().lower(),
    }


def _validate_url(url: str, field: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{field} must be an http(s) URL")
    if not parsed.netloc:
        raise ValueError(f"{field} must include a host")


def _validate_state(s: dict[str, Any]) -> None:
    _validate_url(s["ollama_url"], "ollama_url")
    _validate_url(s["openrouter_base_url"], "openrouter_base_url")
    if not s["ollama_model"] or len(s["ollama_model"]) > 256:
        raise ValueError("ollama_model must be a non-empty string (max 256 chars)")
    if not s["openrouter_model"] or len(s["openrouter_model"]) > 256:
        raise ValueError("openrouter_model must be a non-empty string (max 256 chars)")
    ot = int(s["ollama_timeout"])
    rt = int(s["openrouter_timeout"])
    if not (1 <= ot <= 600 and 1 <= rt <= 600):
        raise ValueError("ollama_timeout and openrouter_timeout must be 1–600 seconds")
    dp = s["default_provider"]
    if dp not in ("ollama", "openrouter"):
        raise ValueError("default_provider must be 'ollama' or 'openrouter'")


def _overlay_file(base: dict[str, Any], path: Path) -> dict[str, Any]:
    out = {**base}
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        log.warning("Ignoring invalid JSON in %s: %s", path, exc)
        return out
    if not isinstance(data, dict):
        return out
    for key in _MERGE_KEYS:
        if key not in data or data[key] is None:
            continue
        if key.endswith("_timeout"):
            out[key] = int(data[key])
        elif key == "openrouter_api_key":
            out[key] = str(data[key]).strip()
        else:
            val = str(data[key]).strip()
            if key.endswith("_url"):
                val = val.rstrip("/")
            out[key] = val
    return out


def init_llm_config() -> None:
    """Load env defaults, overlay persisted file if present. Call once at app startup."""
    global _state
    base = _defaults_from_env()
    path = config_path()
    merged = _overlay_file(base, path) if path.is_file() else base
    try:
        _validate_state(merged)
    except ValueError as exc:
        log.warning(
            "LLM config invalid (%s); using environment defaults only. Path was %s.",
            exc,
            path,
        )
        merged = base
        _validate_state(merged)
    with _lock:
        _state = merged


def get_llm_settings() -> dict[str, Any]:
    """Copy of full settings including OpenRouter API key (server-side only)."""
    with _lock:
        return {**_state}


def _mask_key(key: str) -> tuple[bool, str]:
    if not key:
        return False, ""
    tail = key[-4:] if len(key) >= 4 else key
    return True, "****" + tail


def to_public_config() -> dict[str, Any]:
    """Safe dict for JSON responses (masked API key)."""
    s = get_llm_settings()
    configured, masked = _mask_key(s.get("openrouter_api_key", ""))
    return {
        "ollama_url": s["ollama_url"],
        "ollama_model": s["ollama_model"],
        "ollama_timeout": s["ollama_timeout"],
        "openrouter_base_url": s["openrouter_base_url"],
        "openrouter_model": s["openrouter_model"],
        "openrouter_timeout": s["openrouter_timeout"],
        "openrouter_api_key_masked": masked,
        "openrouter_api_key_configured": configured,
        "default_provider": s["default_provider"],
        "config_file": str(config_path()),
        "precedence": (
            "Environment variables seed defaults. If config_file exists, its values "
            "override env on startup. PUT /api/llm-config updates memory and config_file."
        ),
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def apply_llm_config_update(body: dict[str, Any]) -> dict[str, Any]:
    """Merge JSON body into state, validate, persist. Omit openrouter_api_key to keep."""
    global _state
    with _lock:
        merged = {**_state}

    for key in _STR_KEYS:
        if key in body and body[key] is not None:
            val = str(body[key]).strip()
            if key.endswith("_url"):
                val = val.rstrip("/")
            merged[key] = val

    if "ollama_timeout" in body and body["ollama_timeout"] is not None:
        merged["ollama_timeout"] = int(body["ollama_timeout"])
    if "openrouter_timeout" in body and body["openrouter_timeout"] is not None:
        merged["openrouter_timeout"] = int(body["openrouter_timeout"])

    if "openrouter_api_key" in body:
        raw = body["openrouter_api_key"]
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            merged["openrouter_api_key"] = ""
        else:
            merged["openrouter_api_key"] = str(raw).strip()

    _validate_state(merged)
    path = config_path()
    try:
        _atomic_write_json(path, dict(merged))
    except OSError as exc:
        raise OSError(f"Could not write {path}: {exc}") from exc

    with _lock:
        _state = merged
    return to_public_config()
