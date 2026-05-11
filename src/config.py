"""Configuration & secrets plumbing.

Every secret and tunable the application needs is exposed through one
``Settings`` model and one ``get_settings()`` accessor. Other modules
should never reach into ``st.secrets`` or ``os.environ`` directly — that
keeps the dependency graph small and makes tests trivial to set up.

Values are read from (in priority order, lowest → highest):

1. ``st.secrets`` — Streamlit reads ``.streamlit/secrets.toml`` locally and
   the per-app Secrets editor when deployed to Streamlit Community Cloud.
2. Environment variables (uppercased field name), useful for shells, CI,
   and tests.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Settings(BaseModel):
    """Runtime configuration loaded once per process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    anthropic_api_key: str = Field(..., min_length=1)
    github_token: str = Field(..., min_length=1)
    github_data_repo: str = Field(
        ...,
        min_length=1,
        description="Full name of the private data repo, e.g. 'user/ai-sports-data'.",
    )
    app_password: str = Field(..., min_length=1)

    strava_client_id: Optional[str] = None
    strava_client_secret: Optional[str] = None
    strava_refresh_token: Optional[str] = None

    default_branch: str = "main"
    llm_model: str = "claude-sonnet-4-6"
    agent_max_steps: int = Field(default=6, ge=1, le=20)

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "Settings":
        """Build a Settings from a plain dict, surfacing missing-key errors clearly."""
        known = set(cls.model_fields.keys())
        filtered = {k: v for k, v in mapping.items() if k in known}
        try:
            return cls(**filtered)
        except ValidationError as exc:
            missing: list[str] = []
            for err in exc.errors():
                if err["type"] in {"missing", "string_too_short"} and err["loc"]:
                    missing.append(str(err["loc"][0]))
            if missing:
                raise ValueError(
                    "Missing required configuration key(s): "
                    + ", ".join(sorted(set(missing)))
                    + ". Set them in .streamlit/secrets.toml or as environment variables."
                ) from exc
            raise ValueError(f"Invalid configuration: {exc}") from exc


def _load_st_secrets() -> dict[str, Any]:
    """Pull every known field from Streamlit's secrets store, if available."""
    try:
        import streamlit as st
    except Exception:
        return {}
    mapping: dict[str, Any] = {}
    for key in Settings.model_fields:
        try:
            if key in st.secrets:
                mapping[key] = st.secrets[key]
        except Exception:
            return mapping
    return mapping


def _load_env() -> dict[str, Any]:
    """Pull every known field from environment variables (uppercased)."""
    mapping: dict[str, Any] = {}
    for key in Settings.model_fields:
        env_key = key.upper()
        if env_key in os.environ:
            mapping[key] = os.environ[env_key]
    return mapping


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    mapping: dict[str, Any] = {}
    mapping.update(_load_st_secrets())
    mapping.update(_load_env())
    return Settings.from_mapping(mapping)
