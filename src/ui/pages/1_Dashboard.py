"""Dashboard page — Quick Add, weekly overview, and recent activities.

The first end-to-end vertical slice: the user types a workout, the Parser
Agent turns it into a structured ``ActivitySchema``, the storage service
commits it to the data repo, and it appears in the list below.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import plotly.express as px
import streamlit as st

from src.agents import parser_agent
from src.agents.sync_agent import sync_recent
from src.ui import services as ui_services
from src.ui.auth import require_password
from src.ui.components import activity_card, follow_up_panel, page_header
from src.models.schemas import FollowUpQuestion

require_password()

page_header("Dashboard", "Log a workout and see what you've done this week.")


# --- Strava sync -----------------------------------------------------------

strava_client = ui_services.get_strava_client()
col_sync, col_sync_help = st.columns([1, 4])
with col_sync:
    sync_clicked = st.button(
        "🔄 Sync Strava",
        disabled=strava_client is None,
        width="stretch",
    )
with col_sync_help:
    if strava_client is None:
        st.caption("Strava not configured — add strava_* keys to secrets to enable.")
    else:
        st.caption("Pulls new running/cycling/swim activities since the last sync.")

if sync_clicked and strava_client is not None:
    sync_result = None
    with st.spinner("Syncing with Strava..."):
        try:
            sync_result = sync_recent(
                client=strava_client, storage=ui_services.get_storage()
            )
        except Exception as exc:
            st.error(f"Sync failed: {exc}")
    if sync_result is not None:
        ui_services.clear_activity_caches()
        parts: list[str] = []
        if sync_result.imported:
            parts.append(f"imported {len(sync_result.imported)} new")
        if sync_result.refreshed:
            parts.append(f"refreshed {len(sync_result.refreshed)} existing")
        if sync_result.skipped_existing:
            parts.append(f"skipped {sync_result.skipped_existing} unchanged")
        if sync_result.rate_limited:
            st.error(
                "Strava rate limit hit — sync stopped early. Wait ~15 min and "
                "click Sync again to finish the remaining activities."
            )
            if parts:
                st.info("Before the limit kicked in — " + ", ".join(parts) + ".")
        elif parts:
            st.success("Sync complete — " + ", ".join(parts) + ".")
        else:
            st.info("Nothing to do.")
        for err in sync_result.errors:
            st.warning(err)
        st.rerun()


# --- Quick Add --------------------------------------------------------------

st.subheader("Quick Add")
with st.form("quick_add", clear_on_submit=True):
    quick_add_text = st.text_area(
        "Describe your workout",
        placeholder="e.g. '30 min easy run this morning, felt great'",
        height=100,
    )
    submitted = st.form_submit_button("Submit", type="primary")

if submitted:
    text = quick_add_text.strip()
    if not text:
        st.warning("Type something first.")
    else:
        result = None
        with st.spinner("Parsing..."):
            try:
                result = parser_agent.parse_activity(text)
            except Exception as exc:
                st.error(f"Parser error: {exc}")

        if result is None:
            pass
        elif result.activity is None:
            st.warning(result.fallback_message or "Couldn't parse that — try again.")
        else:
            try:
                with st.spinner("Saving..."):
                    path = ui_services.get_storage().save_activity(result.activity, body=text)
            except Exception as exc:
                st.error(f"Could not save activity: {exc}")
            else:
                ui_services.clear_activity_caches()
                if result.questions:
                    follow_ups = st.session_state.setdefault("follow_ups", {})
                    follow_ups[path] = [q.model_dump() for q in result.questions]
                st.success(f"Saved: {result.activity.title}")
                st.rerun()


# --- Activity list ----------------------------------------------------------

st.subheader("Recent activities")

_PAGE_SIZE = 10
displayed_count = st.session_state.setdefault("dashboard_displayed_count", _PAGE_SIZE)

try:
    activities, total_count = ui_services.list_recent_activities(limit=displayed_count)
except Exception as exc:
    st.error(f"Could not load activities: {exc}")
    activities, total_count = [], 0

if not activities:
    st.info("No activities yet. Add one above or sync from Strava to get started.")
else:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_activities = [a for _, a in activities if a.activity_date >= week_start]
    total_minutes = sum(a.duration_minutes for a in week_activities)

    col_metric, col_chart = st.columns([1, 3])
    with col_metric:
        st.metric(
            "This week",
            f"{total_minutes} min",
            f"{len(week_activities)} session(s)",
        )
    with col_chart:
        if week_activities:
            per_sport: dict[str, int] = defaultdict(int)
            for a in week_activities:
                per_sport[a.sport] += a.duration_minutes
            fig = px.bar(
                x=list(per_sport.keys()),
                y=list(per_sport.values()),
                labels={"x": "sport", "y": "minutes"},
                title="Minutes by sport this week",
            )
            fig.update_layout(height=220, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No activities yet this week.")

    st.divider()

    follow_ups_state: dict[str, list[dict]] = st.session_state.get("follow_ups", {})
    for path, activity in activities:
        clicked = activity_card(activity, path)
        pending = follow_ups_state.get(path)
        if pending:
            follow_up_panel(FollowUpQuestion(**q) for q in pending)
        if clicked:
            st.query_params["path"] = path
            st.session_state["selected_activity_path"] = path
            st.switch_page("pages/2_Activity_Detail.py")

    st.caption(f"Showing {len(activities)} of {total_count} activities.")
    if len(activities) < total_count:
        if st.button(f"Load {min(_PAGE_SIZE, total_count - len(activities))} more"):
            st.session_state["dashboard_displayed_count"] = (
                displayed_count + _PAGE_SIZE
            )
            st.rerun()
