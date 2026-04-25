"""Runtime LLM settings: environment defaults, JSON file overlay, thread-safe updates.

OpenRouter is the only supported provider. Two model roles are configurable:

- ``agent_model``  — drives the tool-calling agent loop. Cheap/fast.
- ``repair_model`` — used by the bounded one-shot SQL repair pass. May be a
  stronger (and more expensive) model. Falls back to ``agent_model`` when unset.

Precedence
----------
1. On startup, values are loaded from environment variables.
2. If ``LLM_CONFIG_PATH`` points to an existing JSON file, its keys overlay the env
   defaults (persisted settings win).
3. ``PUT /api/llm-config`` updates the in-memory state and rewrites that JSON file.

Backward compatibility
----------------------
- The legacy ``openrouter_model`` field is kept as a synonym for ``agent_model``.
  When ``agent_model`` is unset, ``openrouter_model`` is used. When both are set,
  ``agent_model`` wins.
- Legacy Ollama keys (``ollama_url``, ``ollama_model``, ``ollama_timeout``) and
  ``LLM_PROVIDER=ollama`` are silently ignored at startup; a deprecation warning
  is logged once. They no longer appear in API responses.

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

DEFAULT_OPENROUTER_MODELS: tuple[str, ...] = (
    "deepseek/deepseek-v3.2",
    "google/gemini-3.1-flash-lite-preview",
    "minimax/minimax-m2.5",
    "x-ai/grok-4.1-fast",
)

REQUIRED_PROVIDER_KEYS: tuple[str, ...] = ("google", "gpt", "grok", "mistral", "claude")

DEFAULT_MODELS_BY_PROVIDER: dict[str, list[str]] = {
    "google": ["google/gemini-3.1-flash-lite-preview"],
    "gpt": ["openai/gpt-4.1-mini"],
    "grok": ["x-ai/grok-4.1-fast"],
    "mistral": ["mistralai/mistral-7b-instruct:free"],
    "claude": ["anthropic/claude-3.5-sonnet"],
}

_PREFIX_TO_GROUP: dict[str, str] = {
    "google": "google",
    "openai": "gpt",
    "x-ai": "grok",
    "mistralai": "mistral",
    "anthropic": "claude",
}

_lock = threading.RLock()
_state: dict[str, Any] = {}
_models_by_provider: dict[str, list[str]] = {}
_CONFIG_PATH: Path | None = None
_DEPRECATION_LOGGED = False

_MERGE_KEYS = frozenset(
    {
        "openrouter_base_url",
        "openrouter_model",
        "openrouter_models",
        "openrouter_timeout",
        "openrouter_api_key",
        "agent_model",
        "repair_model",
    }
)

_STR_KEYS = frozenset(
    {
        "openrouter_base_url",
        "openrouter_model",
        "agent_model",
        "repair_model",
    }
)

_LEGACY_OLLAMA_ENV_VARS = ("OLLAMA_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT", "LLM_PROVIDER")
_LEGACY_OLLAMA_JSON_KEYS = frozenset(
    {"ollama_url", "ollama_model", "ollama_timeout", "default_provider"}
)


def _openrouter_models_from_env() -> list[str]:
    raw = os.environ.get("OPENROUTER_MODELS", "").strip()
    if not raw:
        return list(DEFAULT_OPENROUTER_MODELS)
    items = [p.strip() for p in raw.split(",") if p.strip()]
    return items if items else list(DEFAULT_OPENROUTER_MODELS)


def _models_by_provider_from_env() -> dict[str, list[str]]:
    """Parse ``OPENROUTER_MODELS_BY_PROVIDER`` env var (JSON object).

    Falls back to :data:`DEFAULT_MODELS_BY_PROVIDER` when unset or invalid.
    Missing provider keys are filled from the defaults so that all
    :data:`REQUIRED_PROVIDER_KEYS` are always present.
    """
    raw = os.environ.get("OPENROUTER_MODELS_BY_PROVIDER", "").strip()
    if not raw:
        return {k: list(v) for k, v in DEFAULT_MODELS_BY_PROVIDER.items()}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Invalid JSON in OPENROUTER_MODELS_BY_PROVIDER; using defaults")
        return {k: list(v) for k, v in DEFAULT_MODELS_BY_PROVIDER.items()}
    if not isinstance(data, dict):
        log.warning("OPENROUTER_MODELS_BY_PROVIDER must be a JSON object; using defaults")
        return {k: list(v) for k, v in DEFAULT_MODELS_BY_PROVIDER.items()}

    result: dict[str, list[str]] = {}
    for key in REQUIRED_PROVIDER_KEYS:
        models = data.get(key)
        if isinstance(models, str):
            parsed = [m.strip() for m in models.split(",") if m.strip()]
        elif isinstance(models, list):
            parsed = [str(m).strip() for m in models if str(m).strip()]
        else:
            parsed = []
        result[key] = parsed if parsed else list(DEFAULT_MODELS_BY_PROVIDER.get(key, []))
    return result


def _infer_provider_group(model_id: str) -> str | None:
    """Map an OpenRouter model id to a provider group key, or ``None``."""
    prefix = model_id.split("/")[0].lower() if "/" in model_id else ""
    return _PREFIX_TO_GROUP.get(prefix)


def coerce_openrouter_models(raw: Any) -> list[str]:
    """Normalize API/JSON input into a non-empty list of model ids."""
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw]
    elif isinstance(raw, str):
        items = [p.strip() for p in raw.split(",")]
    else:
        raise ValueError("openrouter_models must be a list of strings or a comma-separated string")
    items = [x for x in items if x]
    if not items:
        raise ValueError("openrouter_models must contain at least one model id")
    if len(items) > 64:
        raise ValueError("openrouter_models supports at most 64 entries")
    for m in items:
        if len(m) > 256:
            raise ValueError("each openrouter model id must be at most 256 characters")
    return items


def _coerce_optional_model(raw: Any, field: str) -> str:
    """Coerce an optional model id to a stripped string (empty allowed = unset)."""
    if raw is None:
        return ""
    val = str(raw).strip()
    if len(val) > 256:
        raise ValueError(f"{field} must be at most 256 characters")
    return val


def config_path() -> Path:
    """Resolved path to the persisted JSON file (default: beside this package)."""
    global _CONFIG_PATH
    if _CONFIG_PATH is None:
        raw = os.environ.get("LLM_CONFIG_PATH", "").strip()
        if raw:
            _CONFIG_PATH = Path(raw).expanduser().resolve()
        else:
            _CONFIG_PATH = (Path(__file__).resolve().parent.parent / "llm_config.json")
    return _CONFIG_PATH


def _warn_legacy_ollama_env() -> None:
    global _DEPRECATION_LOGGED
    if _DEPRECATION_LOGGED:
        return
    seen = [v for v in _LEGACY_OLLAMA_ENV_VARS if os.environ.get(v, "").strip()]
    if seen:
        log.warning(
            "Ollama support has been removed; ignoring env vars: %s. "
            "Set OPENROUTER_API_KEY (and optionally OPENROUTER_AGENT_MODEL / "
            "OPENROUTER_REPAIR_MODEL) instead.",
            ", ".join(seen),
        )
    _DEPRECATION_LOGGED = True


def _defaults_from_env() -> dict[str, Any]:
    _warn_legacy_ollama_env()
    return {
        "openrouter_base_url": os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        "openrouter_model": (
            os.environ.get("OPENROUTER_MODEL", "").strip()
            or DEFAULT_OPENROUTER_MODELS[0]
        ),
        "openrouter_models": _openrouter_models_from_env(),
        "openrouter_timeout": int(os.environ.get("OPENROUTER_TIMEOUT", "120")),
        "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", "").strip(),
        "agent_model": os.environ.get("OPENROUTER_AGENT_MODEL", "").strip(),
        "repair_model": os.environ.get("OPENROUTER_REPAIR_MODEL", "").strip(),
    }


def _validate_url(url: str, field: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{field} must be an http(s) URL")
    if not parsed.netloc:
        raise ValueError(f"{field} must include a host")


def _validate_state(s: dict[str, Any]) -> None:
    _validate_url(s["openrouter_base_url"], "openrouter_base_url")
    if not s["openrouter_model"] or len(s["openrouter_model"]) > 256:
        raise ValueError("openrouter_model must be a non-empty string (max 256 chars)")
    s["openrouter_models"] = coerce_openrouter_models(s["openrouter_models"])
    rt = int(s["openrouter_timeout"])
    if not (1 <= rt <= 600):
        raise ValueError("openrouter_timeout must be 1–600 seconds")
    s["agent_model"] = _coerce_optional_model(s.get("agent_model"), "agent_model")
    s["repair_model"] = _coerce_optional_model(s.get("repair_model"), "repair_model")


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

    legacy_present = sorted(k for k in _LEGACY_OLLAMA_JSON_KEYS if k in data)
    if legacy_present:
        log.warning(
            "Ignoring legacy Ollama keys in %s: %s", path, ", ".join(legacy_present)
        )

    for key in _MERGE_KEYS:
        if key not in data or data[key] is None:
            continue
        if key == "openrouter_models":
            try:
                out["openrouter_models"] = coerce_openrouter_models(data[key])
            except ValueError:
                log.warning("Ignoring invalid openrouter_models in %s", path)
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
    global _state, _models_by_provider
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
        _models_by_provider = _models_by_provider_from_env()


def get_llm_settings() -> dict[str, Any]:
    """Copy of full settings including OpenRouter API key (server-side only)."""
    with _lock:
        return {**_state}


def resolve_agent_model(override: str | None = None) -> str:
    """Return the model id to use for the agent role, resolved by precedence.

    Precedence: ``override`` > ``agent_model`` > legacy ``openrouter_model``.
    """
    s = get_llm_settings()
    if override and override.strip():
        return override.strip()
    am = (s.get("agent_model") or "").strip()
    if am:
        return am
    return s["openrouter_model"]


def resolve_repair_model(override: str | None = None) -> str:
    """Return the model id to use for the repair role, resolved by precedence.

    Precedence: ``override`` > ``repair_model`` > resolved agent model.
    """
    if override and override.strip():
        return override.strip()
    s = get_llm_settings()
    rm = (s.get("repair_model") or "").strip()
    if rm:
        return rm
    return resolve_agent_model()


def _mask_key(key: str) -> tuple[bool, str]:
    if not key:
        return False, ""
    tail = key[-4:] if len(key) >= 4 else key
    return True, "****" + tail


def to_public_config() -> dict[str, Any]:
    """Safe dict for JSON responses (masked API key, provider-grouped catalog)."""
    s = get_llm_settings()
    configured, masked = _mask_key(s.get("openrouter_api_key", ""))

    with _lock:
        mbp = {k: list(v) for k, v in _models_by_provider.items()}

    resolved = resolve_agent_model()
    group = _infer_provider_group(resolved)
    if group and group in mbp and mbp[group]:
        ui_provider = group
        ui_model = resolved if resolved in mbp[group] else mbp[group][0]
    else:
        # Model is outside the grouped catalog (e.g. deepseek/...).
        # Return empty strings so the UI defaults to "Server default" and does
        # not accidentally override the server's configured model.
        ui_provider = ""
        ui_model = ""

    return {
        "openrouter_base_url": s["openrouter_base_url"],
        "openrouter_model": s["openrouter_model"],
        "openrouter_models": list(s["openrouter_models"]),
        "openrouter_timeout": s["openrouter_timeout"],
        "openrouter_api_key_masked": masked,
        "openrouter_api_key_configured": configured,
        "agent_model": s.get("agent_model", ""),
        "repair_model": s.get("repair_model", ""),
        "resolved_agent_model": resolve_agent_model(),
        "resolved_repair_model": resolve_repair_model(),
        "config_file": str(config_path()),
        "precedence": (
            "Environment variables seed defaults. If config_file exists, its values "
            "override env on startup. PUT /api/llm-config updates memory and config_file."
        ),
        "models_by_provider": mbp,
        "ui_default_provider": ui_provider,
        "ui_default_model": ui_model,
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

    legacy_present = sorted(k for k in _LEGACY_OLLAMA_JSON_KEYS if k in body)
    if legacy_present:
        log.warning(
            "Ignoring legacy Ollama keys in update body: %s", ", ".join(legacy_present)
        )

    for key in _STR_KEYS:
        if key in body and body[key] is not None:
            val = str(body[key]).strip()
            if key.endswith("_url"):
                val = val.rstrip("/")
            merged[key] = val

    if "openrouter_timeout" in body and body["openrouter_timeout"] is not None:
        merged["openrouter_timeout"] = int(body["openrouter_timeout"])

    if "openrouter_models" in body and body["openrouter_models"] is not None:
        merged["openrouter_models"] = coerce_openrouter_models(body["openrouter_models"])

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
