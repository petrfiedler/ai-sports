"""UI-side dependency wiring.

Cached factories for the services and reads the Streamlit pages share across
reruns. Keeping the ``st.cache_*`` glue here lets ``src/services/`` stay
framework-agnostic and testable without importing Streamlit.
"""

from __future__ import annotations

import concurrent.futures
import threading
import concurrent.futures
from datetime import date, timedelta

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

from src.config import get_settings
from src.models.schemas import ActivitySchema, PlanSchema, ProfileSchema
from src.services.storage import GitHubStorage
from src.services.strava_sync import StravaClient


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


@st.cache_resource(show_spinner=False)
def get_strava_client() -> StravaClient | None:
    """Return a process-wide ``StravaClient`` or ``None`` when not configured.

    Strava credentials are optional in :class:`Settings`; the UI surfaces the
    ``None`` case as a disabled Sync button rather than an error.
    """
    settings = get_settings()
    if not (
        settings.strava_client_id
        and settings.strava_client_secret
        and settings.strava_refresh_token
    ):
        return None
    return StravaClient(
        client_id=settings.strava_client_id,
        client_secret=settings.strava_client_secret,
        refresh_token=settings.strava_refresh_token,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def get_activity_streams(strava_id: int) -> dict[str, list[float]]:
    """Fetch HR/altitude/distance/time streams for a Strava activity.

    Cached for an hour so reopening the detail page in the same session
    doesn't re-hit Strava. Returns an empty dict when Strava isn't
    configured or the API call fails.
    """
    client = get_strava_client()
    if client is None:
        return {}
    try:
        return client.activity_streams(strava_id)
    except Exception:
        return {}


@st.cache_data(ttl=60, show_spinner=False)
def list_activity_paths() -> list[str]:
    """All activity paths in the data repo, newest first.

    Cheap relative to loading individual activities — one GitHub directory
    listing call. Cached so pagination doesn't re-list on every "Load more".
    """
    return get_storage().list_activities()


@st.cache_data(ttl=3600, show_spinner=False)
def _load_single_activity(path: str) -> tuple[str, ActivitySchema] | None:
    """Cache the loading of a single activity from GitHub."""
    storage = get_storage()
    try:
        loaded = storage.load_activity(path)
    except Exception:
        return None
    if loaded is None:
        return None
    activity, _body = loaded
    return (path, activity)


def load_activities_slice(
    paths: tuple[str, ...],
) -> list[tuple[str, ActivitySchema]]:
    """Load a specific slice of activity paths concurrently.

    Instead of caching the entire slice as one block, we use a thread pool
    to fetch missing files in parallel, allowing us to cache per-file and
    avoid re-downloading unchanged activities.
    """
    out: list[tuple[str, ActivitySchema]] = []

    ctx = get_script_run_ctx()

    def _run_with_ctx(path: str) -> tuple[str, ActivitySchema] | None:
        add_script_run_ctx(threading.current_thread(), ctx)
        return _load_single_activity(path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for res in executor.map(_run_with_ctx, paths):
            if res is not None:
                out.append(res)

    return out


def list_recent_activities(
    limit: int = 10, offset: int = 0
) -> tuple[list[tuple[str, ActivitySchema]], int]:
    """Return one page of activities plus the total available count.

    Uses :func:`list_activity_paths` for the cheap path index and
    :func:`load_activities_slice` to load only the visible window — so a
    user with 500 stored runs still only fetches the 10 on the page.
    """
    paths = list_activity_paths()
    window = tuple(paths[offset : offset + limit])
    return load_activities_slice(window), len(paths)


def clear_activity_caches(index_only: bool = False) -> None:
    """Invalidate activity caches.

    If index_only is True, we keep the per-file cache intact. This is useful
    when adding a new activity, so we don't have to re-download existing ones.
    """
    list_activity_paths.clear()
    if not index_only:
        _load_single_activity.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_current_plan() -> tuple[PlanSchema, str] | None:
    """Return the most recent plan in the data repo, if any.

    Cached briefly so navigating away and back doesn't re-hit GitHub. Call
    :func:`clear_plan_cache` after writing a plan to invalidate.
    """
    return get_storage().load_current_plan()


def clear_plan_cache() -> None:
    load_current_plan.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_profile() -> ProfileSchema | None:
    """Return the user's stored profile, if present."""
    return get_storage().load_profile()


def clear_profile_cache() -> None:
    load_profile.clear()


def load_recent_activities_for_planning(days: int = 14) -> list[ActivitySchema]:
    """Load activities from the last ``days`` days for the Planner Agent.

    Pulls the cached path index, filters by date prefix, and loads only
    the matching files. Falls back to an empty list on any error so the
    planner can still produce a generic plan.
    """
    cutoff = date.today() - timedelta(days=days)
    try:
        paths = list_activity_paths()
    except Exception:
        return []
    candidates: list[str] = []
    for p in paths:
        stem = p.rsplit("/", 1)[-1]
        date_part = stem[:10]
        try:
            d = date.fromisoformat(date_part)
        except ValueError:
            continue
        if d >= cutoff:
            candidates.append(p)
    if not candidates:
        return []
    loaded = load_activities_slice(tuple(candidates))
    return [a for _p, a in loaded]


def current_monday(today: date | None = None) -> date:
    """Return the Monday of the current week."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def next_monday(today: date | None = None) -> date:
    """Return the Monday of next week (or this Monday if today is Monday)."""
    today = today or date.today()
    if today.weekday() == 0:
        return today
    return today + timedelta(days=(7 - today.weekday()))
