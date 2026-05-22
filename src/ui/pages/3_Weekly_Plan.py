"""Weekly Plan page — generate, view, refine, and tick off the AI plan.

The page tries to load the most recent plan from the data repo. When none
exists it offers a single Generate button. With a plan loaded, each day is
rendered as its own card with a Completed checkbox; flipping the checkbox
writes the plan back. A conversational box at the bottom routes free-text
edits through the Planner Agent's :func:`revise_plan`.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from src.agents import planner_agent
from src.models.schemas import PlanSchema, PlannedActivity, ProfileSchema
from src.ui import services as ui_services
from src.ui.auth import require_password
from src.ui.components import format_date, page_header, render_plan_day

require_password()


def _key_for(plan: PlanSchema) -> str:
    return f"plan_{plan.week_start.isoformat()}"


def _save_plan(plan: PlanSchema, body: str = "") -> bool:
    try:
        with st.spinner("Saving plan..."):
            ui_services.get_storage().save_plan(plan, body)
    except Exception as exc:
        st.error(f"Could not save plan: {exc}")
        return False
    ui_services.clear_plan_cache()
    return True


def _generate(week_start: date) -> None:
    profile = None
    try:
        profile = ui_services.load_profile()
    except Exception as exc:
        st.warning(f"Could not load profile: {exc}")
    if profile is None:
        st.info(
            "No profile yet — generating a generic plan. Fill in the "
            "**Profile** page for plans tailored to your goals."
        )
        profile = ProfileSchema()

    try:
        recent = ui_services.load_recent_activities_for_planning()
    except Exception:
        recent = []

    result = None
    with st.spinner("Generating plan..."):
        try:
            result = planner_agent.generate_plan(profile, recent, week_start)
        except Exception as exc:
            st.error(f"Planner error: {exc}")
    if result is None:
        return
    if result.plan is None:
        st.warning(result.fallback_message or "Couldn't generate a plan.")
        return

    body = result.plan.rationale or ""
    if _save_plan(result.plan, body):
        st.success(f"Plan generated for week of {format_date(result.plan.week_start)}.")
        st.rerun()


def _apply_revision(current: PlanSchema, instruction: str) -> None:
    profile = None
    try:
        profile = ui_services.load_profile()
    except Exception:
        pass

    result = None
    with st.spinner("Revising plan..."):
        try:
            result = planner_agent.revise_plan(current, instruction, profile=profile)
        except Exception as exc:
            st.error(f"Reviser error: {exc}")

    if result is None:
        return
    if result.plan is None or result.plan is current:
        st.warning(result.fallback_message or "Couldn't apply that edit.")
        return
    if result.fallback_message:
        st.warning(result.fallback_message)
        return

    body = result.plan.rationale or ""
    if _save_plan(result.plan, body):
        st.success("Plan updated.")
        st.rerun()


def _toggle_completion(
    current: PlanSchema, body: str, target: PlannedActivity, completed: bool
) -> None:
    updated_activities: list[PlannedActivity] = []
    flipped = False
    for a in current.activities:
        if not flipped and a == target:
            updated_activities.append(a.model_copy(update={"completed": completed}))
            flipped = True
        else:
            updated_activities.append(a)
    updated = current.model_copy(update={"activities": updated_activities})
    if _save_plan(updated, body):
        st.rerun()


page_header("Weekly Plan", "Your AI-generated training week.")

try:
    loaded = ui_services.load_current_plan()
except Exception as exc:
    st.error(f"Could not load plan: {exc}")
    st.stop()

if loaded is None:
    next_mon = ui_services.next_monday()
    st.info(
        f"No plan yet. Generate one for the week of **{format_date(next_mon)}** "
        "(Monday) — it'll be based on your profile and recent activities."
    )
    if st.button("Generate plan", type="primary"):
        _generate(next_mon)
    st.stop()

plan, body = loaded
key = _key_for(plan)

# --- Header ---------------------------------------------------------------

week_end = plan.week_start + timedelta(days=6)
st.subheader(f"Week of {format_date(plan.week_start)} → {format_date(week_end)}")

total_minutes = sum(a.duration_minutes or 0 for a in plan.activities)
completed_count = sum(1 for a in plan.activities if a.completed)
col_a, col_b, col_c = st.columns(3)
col_a.metric("Planned sessions", str(len(plan.activities)))
col_b.metric("Total minutes", f"{total_minutes} min")
col_c.metric(
    "Completed",
    f"{completed_count} / {len(plan.activities)}",
)

if plan.rationale:
    with st.expander("Why this structure?", expanded=False):
        st.markdown(plan.rationale)

st.divider()

# --- Day cards ------------------------------------------------------------

sorted_activities = sorted(plan.activities, key=lambda a: a.day)
for i, planned in enumerate(sorted_activities):
    new_state = render_plan_day(planned, key_prefix=f"{key}_{i}")
    if new_state is not None:
        _toggle_completion(plan, body, planned, new_state)

if not sorted_activities:
    st.info("This plan has no sessions yet — generate a new one or revise it below.")

st.divider()

# --- Conversational revise -------------------------------------------------

st.markdown("**Adjust the plan**")
with st.form("revise_plan", clear_on_submit=True):
    instruction = st.text_input(
        "Edit instruction",
        placeholder="e.g. 'move Tuesday's run to Wednesday'",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("Apply", type="primary")

if submitted:
    text = instruction.strip()
    if not text:
        st.warning("Type the change you want first.")
    else:
        _apply_revision(plan, text)

st.divider()

# --- Regenerate ------------------------------------------------------------

with st.popover("🔁 Regenerate from scratch"):
    st.warning("This overwrites the current plan for this week.")
    if st.button("Confirm regenerate", type="primary", key="confirm_regenerate"):
        _generate(plan.week_start)
