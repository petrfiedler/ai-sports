"""Activity Detail page — view, edit, revise, and delete a single activity.

The path is read from ``?path=`` query param (set by the Dashboard when the
user clicks a card) and falls back to ``session_state["selected_activity_path"]``
for in-app navigation. Edits route through the Reviser Agent and write back
to the same file, so a typo fix is one commit, not a new file.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from src.agents import parser_agent
from src.models.schemas import ActivitySchema, FollowUpQuestion, SportType
from src.ui import services as ui_services
from src.ui.auth import require_password
from src.ui.components import (
    format_date,
    page_header,
    render_endurance_charts,
    render_followups,
    render_lap_bars,
    render_lap_table,
    render_photo_gallery,
    render_route_map,
    render_streams_charts,
    render_strength_table,
    sport_icon,
)

require_password()


_ENDURANCE_SPORTS = {
    SportType.RUNNING.value,
    SportType.CYCLING.value,
    SportType.SWIMMING.value,
    SportType.HIKING.value,
    SportType.WALKING.value,
}


def _resolve_path() -> str | None:
    qp = st.query_params.get("path")
    if isinstance(qp, list):
        qp = qp[0] if qp else None
    if qp:
        st.session_state["selected_activity_path"] = qp
        return qp
    return st.session_state.get("selected_activity_path")


def _apply_revision(
    activity: ActivitySchema, body: str, path: str, instruction: str
) -> bool:
    """Run the reviser, persist on success, return True iff the page should rerun."""
    storage = ui_services.get_storage()
    result = None
    with st.spinner("Revising..."):
        try:
            result = parser_agent.revise_activity(activity, instruction)
        except Exception as exc:
            st.error(f"Reviser error: {exc}")

    if result is None:
        return False
    if result.fallback_message and result.activity is activity:
        st.warning(result.fallback_message)
        return False
    if result.activity is None:
        st.warning(result.fallback_message or "Couldn't apply that edit.")
        return False

    try:
        storage.update_activity(path, result.activity, body)
    except Exception as exc:
        st.error(f"Could not save: {exc}")
        return False

    ui_services.clear_activity_caches()
    st.success("Updated.")
    return True


path = _resolve_path()
if not path:
    page_header("Activity Detail", "Open an activity from the Dashboard.")
    st.info("No activity selected. Click 'Open' on a card to see details here.")
    st.stop()

storage = ui_services.get_storage()

try:
    loaded = storage.load_activity(path)
except Exception as exc:
    page_header("Activity Detail")
    st.error(f"Could not load activity: {exc}")
    st.stop()

if loaded is None:
    page_header("Activity Detail")
    st.warning("That activity no longer exists.")
    st.stop()

activity, body = loaded

# --- Header ----------------------------------------------------------------

icon = sport_icon(activity.sport)
page_header(f"{icon}  {activity.title}", format_date(activity.activity_date))

chips: list[str] = [f"{activity.duration_minutes} min"]
if activity.location:
    chips.append(f"📍 {activity.location}")
if activity.intensity:
    chips.append(f"intensity: {activity.intensity}")
if activity.rpe:
    chips.append(f"RPE {activity.rpe}")
st.caption("  ·  ".join(chips))

if activity.summary:
    st.text(activity.summary)

st.divider()

# --- Sport-conditional body ------------------------------------------------

if activity.sport == SportType.STRENGTH.value:
    render_strength_table(activity.exercises)
elif activity.sport in _ENDURANCE_SPORTS:
    render_endurance_charts(activity.metrics)

if activity.metrics:
    # Live HR + elevation traces from Strava — only fetched once the user
    # opens the detail page so list views stay cheap.
    if activity.metrics.strava_id:
        streams = ui_services.get_activity_streams(activity.metrics.strava_id)
        render_streams_charts(streams)
    render_lap_bars(activity.metrics.laps)
    render_lap_table(activity.metrics.laps)
    render_route_map(activity.metrics.map_polyline)
    render_photo_gallery(activity.metrics.photo_urls)

if activity.notes:
    st.markdown(activity.notes)

if body and body.strip():
    with st.expander("Original note", expanded=False):
        st.markdown(body)

st.divider()

# --- Follow-up Q&A ---------------------------------------------------------

follow_ups_state: dict[str, list[dict]] = st.session_state.setdefault("follow_ups", {})
pending = follow_ups_state.get(path)
if pending:
    questions = [FollowUpQuestion(**q) for q in pending]
    answers = render_followups(questions, key_prefix=path)
    col_skip, _ = st.columns([1, 5])
    with col_skip:
        if st.button("Skip", key=f"skip_{path}"):
            follow_ups_state.pop(path, None)
            st.rerun()
    if answers:
        lines = [f"- {f}: {v}" for f, v in answers.items()]
        instruction = "Update the activity with these answers:\n" + "\n".join(lines)
        if _apply_revision(activity, body, path, instruction):
            follow_ups_state.pop(path, None)
            st.rerun()

# --- Master edit prompt ----------------------------------------------------

st.markdown("**Tell the AI what to fix**")
with st.form("revise_form", clear_on_submit=True):
    instruction = st.text_input(
        "Edit instruction",
        placeholder="e.g. 'those were Bulgarian split squats'",
        label_visibility="collapsed",
    )
    submit_edit = st.form_submit_button("Apply", type="primary")

if submit_edit:
    text = instruction.strip()
    if not text:
        st.warning("Type the change you want first.")
    elif _apply_revision(activity, body, path, text):
        st.rerun()

st.divider()

# --- Delete ----------------------------------------------------------------

with st.popover("🗑️ Delete activity"):
    st.warning("This permanently deletes the file from the data repo.")
    if st.button("Confirm delete", type="primary", key="confirm_delete"):
        try:
            storage.delete_activity(path)
        except Exception as exc:
            st.error(f"Delete failed: {exc}")
        else:
            ui_services.clear_activity_caches()
            st.session_state.pop("selected_activity_path", None)
            follow_ups_state.pop(path, None)
            try:
                del st.query_params["path"]
            except KeyError:
                pass
            st.success("Deleted.")
            st.switch_page("pages/1_Dashboard.py")
