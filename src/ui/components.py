"""Reusable Streamlit UI components.

Phase 5 added ``activity_card`` and ``follow_up_panel``. Phase 6 adds
``render_strength_table``, ``render_endurance_charts``, ``render_followups``;
Phase 9 will add ``render_plan_day``.
"""

from __future__ import annotations

from typing import Iterable, Optional

import streamlit as st

from src.models.schemas import (
    ActivitySchema,
    EnduranceMetrics,
    Exercise,
    FollowUpQuestion,
    SportType,
)


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


def render_strength_table(exercises: list[Exercise]) -> None:
    """Render strength exercises as one table per exercise.

    Each table lists set #, reps, weight (kg), duration (s), rest (s).
    Empty cells display as ``—``. No-op when ``exercises`` is empty.
    """
    if not exercises:
        return
    for ex in exercises:
        st.markdown(f"**{ex.name}**")
        if ex.notes:
            st.caption(ex.notes)
        rows: list[dict[str, str]] = []
        for i, s in enumerate(ex.sets, start=1):
            rows.append(
                {
                    "Set": str(i),
                    "Reps": str(s.reps) if s.reps is not None else "—",
                    "Weight (kg)": (
                        f"{s.weight_kg:g}" if s.weight_kg is not None else "—"
                    ),
                    "Duration (s)": (
                        str(s.duration_seconds)
                        if s.duration_seconds is not None
                        else "—"
                    ),
                    "Rest (s)": (
                        str(s.rest_seconds) if s.rest_seconds is not None else "—"
                    ),
                }
            )
        if rows:
            st.table(rows)


def render_endurance_charts(metrics: Optional[EnduranceMetrics]) -> None:
    """Render KPI tiles for an endurance activity.

    The current schema only stores aggregates (no time-series), so this is
    a metric panel rather than literal charts. No-op when ``metrics`` is
    ``None`` or every field is empty.
    """
    if metrics is None:
        return
    tiles: list[tuple[str, str]] = []
    if metrics.distance_km is not None:
        tiles.append(("Distance", f"{metrics.distance_km:g} km"))
    if metrics.avg_pace:
        tiles.append(("Avg pace", metrics.avg_pace))
    if metrics.avg_speed_kmh is not None:
        tiles.append(("Avg speed", f"{metrics.avg_speed_kmh:g} km/h"))
    if metrics.avg_heart_rate is not None:
        tiles.append(("Avg HR", f"{metrics.avg_heart_rate} bpm"))
    if metrics.max_heart_rate is not None:
        tiles.append(("Max HR", f"{metrics.max_heart_rate} bpm"))
    if metrics.elevation_gain_m is not None:
        tiles.append(("Elevation", f"{metrics.elevation_gain_m:g} m"))
    if metrics.calories is not None:
        tiles.append(("Calories", str(metrics.calories)))

    if not tiles:
        return

    cols = st.columns(min(len(tiles), 4))
    for i, (label, value) in enumerate(tiles):
        with cols[i % len(cols)]:
            st.metric(label, value)


def render_followups(
    questions: list[FollowUpQuestion], *, key_prefix: str
) -> Optional[dict[str, str]]:
    """Render a Q&A form for pending follow-up questions.

    Returns a dict ``{field: answer}`` (skipping blank answers) when the
    user submits the form, otherwise ``None``. ``key_prefix`` namespaces
    the widget keys so multiple instances can coexist within a session.
    """
    if not questions:
        return None

    st.markdown("**Follow-up questions**")
    answers: dict[str, str] = {}
    with st.form(f"{key_prefix}_followups"):
        for i, q in enumerate(questions):
            answers[q.field] = st.text_input(
                q.question,
                key=f"{key_prefix}_fu_{i}_{q.field}",
            )
        submitted = st.form_submit_button("Submit answers", type="primary")
    if not submitted:
        return None
    return {f: v.strip() for f, v in answers.items() if v and v.strip()}
