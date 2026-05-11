"""UI-side dependency wiring.

Cached factories for the services and reads the Streamlit pages share across
reruns. Keeping the ``st.cache_*`` glue here lets ``src/services/`` stay
framework-agnostic and testable without importing Streamlit.
"""

from __future__ import annotations

import streamlit as st

from src.config import get_settings
from src.models.schemas import ActivitySchema
from src.services.storage import GitHubStorage


@st.cache_resource(show_spinner=False)
def get_storage() -> GitHubStorage:
    """Return a process-wide ``GitHubStorage`` instance.

    Cached as a Streamlit resource so the underlying PyGithub client is
    reused across reruns within the same session.
    """
    settings = get_settings()
    return GitHubStorage.from_token(
        repo_full_name=settings.github_data_repo,
        token=settings.github_token,
        branch=settings.default_branch,
    )


@st.cache_data(ttl=30, show_spinner=False)
def list_recent_activities(limit: int = 30) -> list[tuple[str, ActivitySchema]]:
    """Return ``(path, activity)`` pairs for the most recent activities.

    Cached for 30s so casual reruns don't re-hit GitHub for every interaction.
    Call ``list_recent_activities.clear()`` after a write to force a refresh.
    Files that fail to load are skipped silently.
    """
    storage = get_storage()
    out: list[tuple[str, ActivitySchema]] = []
    for path in storage.list_activities()[:limit]:
        try:
            loaded = storage.load_activity(path)
        except Exception:
            continue
        if loaded is None:
            continue
        activity, _body = loaded
        out.append((path, activity))
    return out
