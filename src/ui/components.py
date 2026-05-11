"""Reusable Streamlit UI components.

Phase 5 adds ``activity_card`` and ``follow_up_panel``. Phase 6 will add
``render_strength_table``, ``render_endurance_charts``, ``render_followups``;
Phase 9 will add ``render_plan_day``.
"""

from __future__ import annotations

from typing import Iterable

import streamlit as st

from src.models.schemas import ActivitySchema, FollowUpQuestion, SportType


_SPORT_ICONS: dict[str, str] = {
    SportType.RUNNING.value: "🏃",
    SportType.CYCLING.value: "🚴",
    SportType.SWIMMING.value: "🏊",
    SportType.BOULDERING.value: "🧗",
    SportType.CLIMBING.value: "🧗",
    SportType.STRENGTH.value: "🏋️",
    SportType.YOGA.value: "🧘",
    SportType.HIKING.value: "🥾",
    SportType.WALKING.value: "🚶",
    SportType.OTHER.value: "🏅",
}


def page_header(title: str, subtitle: str | None = None) -> None:
    """Render a consistent page header across pages."""
    st.header(title)
    if subtitle:
        st.caption(subtitle)


def sport_icon(sport: str | SportType) -> str:
    """Return a single-emoji icon for a sport. Falls back to a medal."""
    key = sport.value if isinstance(sport, SportType) else str(sport)
    return _SPORT_ICONS.get(key, _SPORT_ICONS[SportType.OTHER.value])


def activity_card(activity: ActivitySchema, path: str) -> bool:
    """Render a one-row card for an activity. Returns ``True`` when opened.

    The card surfaces sport icon, title, date, duration, and an optional RPE
    badge; the caller is responsible for navigation when the return value is
    truthy.
    """
    icon = sport_icon(activity.sport)
    when = activity.activity_date.isoformat()
    duration_str = f"{activity.duration_minutes} min"
    rpe_str = f"  ·  RPE {activity.rpe}" if activity.rpe else ""

    with st.container(border=True):
        col_main, col_action = st.columns([5, 1])
        with col_main:
            st.markdown(f"### {icon}  {activity.title}")
            st.caption(f"{when}  ·  {duration_str}{rpe_str}")
        with col_action:
            return st.button("Open", key=f"open_{path}", width="stretch")


def follow_up_panel(questions: Iterable[FollowUpQuestion]) -> None:
    """Render a collapsible panel listing pending follow-up questions."""
    qs = list(questions)
    if not qs:
        return
    label = f"❓ {len(qs)} follow-up question(s) — open the detail page to answer"
    with st.expander(label, expanded=False):
        for q in qs:
            st.markdown(f"- **{q.field}**: {q.question}")
