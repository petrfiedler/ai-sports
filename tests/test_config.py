"""Tests for src.config."""

from __future__ import annotations

import pytest

from src.config import Settings, get_settings

REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "sk-test",
    "GITHUB_TOKEN": "ghp_test",
    "GITHUB_DATA_REPO": "user/data",
    "APP_PASSWORD": "secret",
}


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with no env vars and no st.secrets influence."""
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setattr("src.config._load_st_secrets", lambda: {})
    get_settings.cache_clear()


# --- Settings.from_mapping -------------------------------------------------


def test_from_mapping_with_required_only_uses_defaults() -> None:
    s = Settings.from_mapping(
        {
            "anthropic_api_key": "sk",
            "github_token": "ghp",
            "github_data_repo": "u/r",
            "app_password": "pw",
        }
    )
    assert s.anthropic_api_key == "sk"
    assert s.github_data_repo == "u/r"
    assert s.default_branch == "main"
    assert s.llm_model == "claude-sonnet-4-6"
    assert s.agent_max_steps == 6
    assert s.strava_client_id is None


def test_from_mapping_missing_required_raises_valueerror_not_keyerror() -> None:
    with pytest.raises(ValueError, match="Missing required configuration") as exc_info:
        Settings.from_mapping({"anthropic_api_key": "sk"})
    msg = str(exc_info.value)
    assert "github_token" in msg
    assert "github_data_repo" in msg
    assert "app_password" in msg


def test_from_mapping_empty_string_counted_as_missing() -> None:
    with pytest.raises(ValueError, match="Missing required configuration") as exc_info:
        Settings.from_mapping(
            {
                "anthropic_api_key": "",
                "github_token": "ghp",
                "github_data_repo": "u/r",
                "app_password": "pw",
            }
        )
    assert "anthropic_api_key" in str(exc_info.value)


def test_from_mapping_ignores_unknown_keys() -> None:
    s = Settings.from_mapping(
        {
            "anthropic_api_key": "sk",
            "github_token": "ghp",
            "github_data_repo": "u/r",
            "app_password": "pw",
            "totally_unrelated": "ignored",
        }
    )
    assert s.anthropic_api_key == "sk"


def test_agent_max_steps_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        Settings.from_mapping(
            {
                "anthropic_api_key": "sk",
                "github_token": "ghp",
                "github_data_repo": "u/r",
                "app_password": "pw",
                "agent_max_steps": 0,
            }
        )


def test_settings_is_frozen() -> None:
    s = Settings.from_mapping(
        {
            "anthropic_api_key": "sk",
            "github_token": "ghp",
            "github_data_repo": "u/r",
            "app_password": "pw",
        }
    )
    with pytest.raises(Exception):
        s.app_password = "other"  # type: ignore[misc]


# --- get_settings ----------------------------------------------------------


def test_get_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    s = get_settings()
    assert s.app_password == "secret"
    assert s.github_data_repo == "user/data"
    assert s.anthropic_api_key == "sk-test"


def test_get_settings_raises_clear_error_when_required_missing() -> None:
    with pytest.raises(ValueError, match="Missing required configuration"):
        get_settings()


def test_get_settings_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LLM_MODEL", "claude-opus-4-7")
    monkeypatch.setenv("AGENT_MAX_STEPS", "10")
    s = get_settings()
    assert s.llm_model == "claude-opus-4-7"
    assert s.agent_max_steps == 10


def test_get_settings_env_overrides_st_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.config._load_st_secrets",
        lambda: {
            "anthropic_api_key": "from-secrets",
            "github_token": "ghp",
            "github_data_repo": "u/r",
            "app_password": "pw",
        },
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    get_settings.cache_clear()
    s = get_settings()
    assert s.anthropic_api_key == "from-env"


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    a = get_settings()
    b = get_settings()
    assert a is b
