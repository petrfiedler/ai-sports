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
from src.ui import services as ui_services
from src.ui.auth import require_password
from src.ui.components import activity_card, follow_up_panel, page_header
from src.models.schemas import FollowUpQuestion

require_password()

page_header("Dashboard", "Log a workout and see what you've done this week.")


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
                ui_services.list_recent_activities.clear()
                if result.questions:
                    follow_ups = st.session_state.setdefault("follow_ups", {})
                    follow_ups[path] = [q.model_dump() for q in result.questions]
                st.success(f"Saved: {result.activity.title}")
                st.rerun()


# --- Activity list ----------------------------------------------------------

st.subheader("Recent activities")

try:
    activities = ui_services.list_recent_activities()
except Exception as exc:
    st.error(f"Could not load activities: {exc}")
    activities = []

if not activities:
    st.info("No activities yet. Add one above to get started.")
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
