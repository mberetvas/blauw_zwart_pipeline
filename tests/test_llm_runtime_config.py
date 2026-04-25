"""Unit tests for sql_agent.llm_runtime_config: env defaults, file overlay, updates."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reload the runtime config module with a clean env scoped to tmp_path."""
    config_path = tmp_path / "llm_config.json"
    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-v3.2")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "120")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-default")
    monkeypatch.delenv("OPENROUTER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_REPAIR_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODELS", raising=False)
    monkeypatch.delenv("OPENROUTER_MODELS_BY_PROVIDER", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    import frontend_app.sql_agent.llm_runtime_config as mod

    importlib.reload(mod)
    mod.init_llm_config()
    return mod


# ---------------------------------------------------------------------------
# coerce_openrouter_models
# ---------------------------------------------------------------------------


def test_coerce_models_from_list(cfg) -> None:
    assert cfg.coerce_openrouter_models(["a/b", "c/d"]) == ["a/b", "c/d"]


def test_coerce_models_from_csv_string(cfg) -> None:
    assert cfg.coerce_openrouter_models("a/b, c/d , ") == ["a/b", "c/d"]


def test_coerce_models_rejects_empty_list(cfg) -> None:
    with pytest.raises(ValueError, match=r"at least one"):
        cfg.coerce_openrouter_models([])


def test_coerce_models_rejects_too_many(cfg) -> None:
    with pytest.raises(ValueError, match=r"at most 64"):
        cfg.coerce_openrouter_models([f"x/{i}" for i in range(65)])


def test_coerce_models_rejects_too_long_id(cfg) -> None:
    with pytest.raises(ValueError, match=r"at most 256"):
        cfg.coerce_openrouter_models(["a" * 257])


def test_coerce_models_rejects_wrong_type(cfg) -> None:
    with pytest.raises(ValueError, match=r"list of strings"):
        cfg.coerce_openrouter_models(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# init_llm_config — env defaults
# ---------------------------------------------------------------------------


def test_init_uses_env_defaults_when_no_file(cfg) -> None:
    s = cfg.get_llm_settings()
    assert s["openrouter_base_url"] == "https://openrouter.ai/api/v1"
    assert s["openrouter_model"] == "deepseek/deepseek-v3.2"
    assert s["openrouter_timeout"] == 120
    assert s["openrouter_api_key"] == "sk-default"


def test_resolve_agent_model_falls_back_to_openrouter_model(cfg) -> None:
    assert cfg.resolve_agent_model() == "deepseek/deepseek-v3.2"


def test_resolve_repair_model_falls_back_to_agent_model(cfg) -> None:
    assert cfg.resolve_repair_model() == "deepseek/deepseek-v3.2"


def test_resolve_agent_model_override_wins(cfg) -> None:
    assert cfg.resolve_agent_model("override/model") == "override/model"


def test_resolve_repair_model_override_wins(cfg) -> None:
    assert cfg.resolve_repair_model("override/repair") == "override/repair"


# ---------------------------------------------------------------------------
# File overlay
# ---------------------------------------------------------------------------


def test_file_overlay_persists_and_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "llm_config.json"
    config_path.write_text(
        json.dumps(
            {
                "openrouter_base_url": "https://openrouter.ai/api/v1/",
                "openrouter_model": "openai/gpt-4.1-mini",
                "openrouter_timeout": 60,
                "openrouter_api_key": "sk-from-file",
                "agent_model": "openai/gpt-4.1-mini",
                "repair_model": "anthropic/claude-3.5-sonnet",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-v3.2")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "120")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-default")
    monkeypatch.delenv("OPENROUTER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_REPAIR_MODEL", raising=False)

    import frontend_app.sql_agent.llm_runtime_config as mod

    importlib.reload(mod)
    mod.init_llm_config()

    s = mod.get_llm_settings()
    assert s["openrouter_model"] == "openai/gpt-4.1-mini"
    assert s["openrouter_timeout"] == 60
    assert s["openrouter_api_key"] == "sk-from-file"
    assert mod.resolve_repair_model() == "anthropic/claude-3.5-sonnet"
    # Trailing slash stripped on URL
    assert s["openrouter_base_url"] == "https://openrouter.ai/api/v1"


def test_file_overlay_invalid_json_falls_back_to_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "llm_config.json"
    config_path.write_text("{not json", encoding="utf-8")

    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-v3.2")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "120")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-default")
    monkeypatch.delenv("OPENROUTER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_REPAIR_MODEL", raising=False)

    import frontend_app.sql_agent.llm_runtime_config as mod

    importlib.reload(mod)
    mod.init_llm_config()

    assert mod.get_llm_settings()["openrouter_model"] == "deepseek/deepseek-v3.2"


def test_file_overlay_ignores_legacy_ollama_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "llm_config.json"
    config_path.write_text(
        json.dumps(
            {
                "openrouter_model": "openai/gpt-4.1-mini",
                "ollama_url": "http://ollama:11434",
                "ollama_model": "phi3",
                "default_provider": "ollama",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-default")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-v3.2")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "120")

    import frontend_app.sql_agent.llm_runtime_config as mod

    importlib.reload(mod)
    mod.init_llm_config()

    s = mod.get_llm_settings()
    assert s["openrouter_model"] == "openai/gpt-4.1-mini"
    assert "ollama_url" not in s
    assert "default_provider" not in s


# ---------------------------------------------------------------------------
# apply_llm_config_update
# ---------------------------------------------------------------------------


def test_apply_update_persists_and_returns_masked(cfg, tmp_path: Path) -> None:
    body = {
        "openrouter_model": "openai/gpt-4.1-mini",
        "openrouter_timeout": 90,
        "openrouter_api_key": "sk-update-1234",
        "agent_model": "openai/gpt-4.1-mini",
        "repair_model": "anthropic/claude-3.5-sonnet",
    }
    public = cfg.apply_llm_config_update(body)
    assert public["openrouter_api_key_masked"] == "****1234"
    assert public["openrouter_api_key_configured"] is True
    assert public["agent_model"] == "openai/gpt-4.1-mini"

    # Persisted to disk
    on_disk = json.loads(cfg.config_path().read_text(encoding="utf-8"))
    assert on_disk["openrouter_api_key"] == "sk-update-1234"


def test_apply_update_omitting_api_key_keeps_existing(cfg) -> None:
    cfg.apply_llm_config_update({"openrouter_api_key": "sk-keep-9876"})
    cfg.apply_llm_config_update({"openrouter_model": "openai/gpt-4.1-mini"})
    s = cfg.get_llm_settings()
    assert s["openrouter_api_key"] == "sk-keep-9876"


def test_apply_update_clearing_api_key_with_empty_string(cfg) -> None:
    cfg.apply_llm_config_update({"openrouter_api_key": "sk-then-clear"})
    cfg.apply_llm_config_update({"openrouter_api_key": ""})
    assert cfg.get_llm_settings()["openrouter_api_key"] == ""


def test_apply_update_validates_url(cfg) -> None:
    with pytest.raises(ValueError, match=r"http\(s\) URL"):
        cfg.apply_llm_config_update({"openrouter_base_url": "ftp://nope"})


def test_apply_update_validates_timeout_range(cfg) -> None:
    with pytest.raises(ValueError, match=r"1.{1,3}600"):
        cfg.apply_llm_config_update({"openrouter_timeout": 0})


def test_apply_update_ignores_legacy_ollama_keys(cfg) -> None:
    cfg.apply_llm_config_update({"ollama_url": "http://x", "default_provider": "ollama"})
    s = cfg.get_llm_settings()
    assert "ollama_url" not in s


def test_to_public_config_masks_short_api_key(cfg) -> None:
    cfg.apply_llm_config_update({"openrouter_api_key": "ab"})
    public = cfg.to_public_config()
    assert public["openrouter_api_key_configured"] is True
    assert public["openrouter_api_key_masked"] == "****ab"


def test_to_public_config_not_configured_when_no_key(cfg) -> None:
    cfg.apply_llm_config_update({"openrouter_api_key": ""})
    public = cfg.to_public_config()
    assert public["openrouter_api_key_configured"] is False
    assert public["openrouter_api_key_masked"] == ""


def test_to_public_config_includes_models_by_provider(cfg) -> None:
    public = cfg.to_public_config()
    for key in ("google", "gpt", "grok", "mistral", "claude"):
        assert key in public["models_by_provider"]


def test_models_by_provider_from_env_invalid_json_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_MODELS_BY_PROVIDER", "{not json")
    import frontend_app.sql_agent.llm_runtime_config as mod

    importlib.reload(mod)
    out = mod._models_by_provider_from_env()
    assert set(out.keys()) == set(mod.REQUIRED_PROVIDER_KEYS)


def test_models_by_provider_from_env_non_object_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_MODELS_BY_PROVIDER", "[1,2,3]")
    import frontend_app.sql_agent.llm_runtime_config as mod

    importlib.reload(mod)
    out = mod._models_by_provider_from_env()
    assert set(out.keys()) == set(mod.REQUIRED_PROVIDER_KEYS)


def test_models_by_provider_accepts_csv_per_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OPENROUTER_MODELS_BY_PROVIDER",
        json.dumps({"gpt": "openai/a, openai/b"}),
    )
    import frontend_app.sql_agent.llm_runtime_config as mod

    importlib.reload(mod)
    out = mod._models_by_provider_from_env()
    assert out["gpt"] == ["openai/a", "openai/b"]
