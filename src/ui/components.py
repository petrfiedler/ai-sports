"""Reusable Streamlit UI components.

Phase 5 added ``activity_card`` and ``follow_up_panel``. Phase 6 adds
``render_strength_table``, ``render_endurance_charts``, ``render_followups``.
Phase 9 adds ``render_plan_day``.
"""

from __future__ import annotations

import datetime
from typing import Iterable, Optional

import streamlit as st

from src.models.schemas import (
    ActivitySchema,
    EnduranceMetrics,
    Exercise,
    FollowUpQuestion,
    Lap,
    PlannedActivity,
    SportType,
)


def format_date(d: datetime.date) -> str:
    """Format a date based on user's relative rules."""
    today = datetime.date.today()
    delta_days = (today - d).days

    if delta_days == 0:
        return f"Today, {d.strftime('%B')} {d.day}"
    elif delta_days == 1:
        return f"Yesterday, {d.strftime('%B')} {d.day}"
    elif 1 < delta_days <= 6:
        # In last 7 days (and not today or yesterday)
        return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"
    elif d.year == today.year:
        return f"{d.strftime('%B')} {d.day}"
    else:
        return f"{d.strftime('%B')} {d.day}, {d.year}"


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
    when = format_date(activity.activity_date)
    duration_str = f"{activity.duration_minutes} min"
    parts = [when, duration_str]
    if activity.location:
        parts.append(f"📍 {activity.location}")
    if activity.rpe:
        parts.append(f"RPE {activity.rpe}")
    caption = "  ·  ".join(parts)

    with st.container(border=True):
        st.markdown(
            f'<h3 style="margin-top: 0; padding-top: 4px; padding-bottom: 4px;">{icon}  {activity.title}</h3>',
            unsafe_allow_html=True,
        )
        st.caption(caption)
        if activity.summary:
            st.text(activity.summary)
        if activity.metrics and activity.metrics.photo_urls:
            imgs_html = "".join(
                f'<img src="{url}" style="height: 120px; flex-shrink: 0; margin-right: 8px; border-radius: 6px;">'
                for url in activity.metrics.photo_urls
            )
            st.markdown(
                f'<div style="display: flex; overflow: hidden; width: 100%; margin-top: 0px; margin-bottom: 16px;">{imgs_html}</div>',
                unsafe_allow_html=True,
            )

        # We put a hidden button here that the JS will virtually click
        btn_container = st.empty()
        with btn_container:
            clicked = st.button("Open", key=f"open_{path}", help="Hidden click target")

        # JS hack to simulate a click on the button when the parent container is clicked.
        # We also hide the iframe container and the button container to eliminate extra whitespace.
        st.iframe(
            """
            <script>
            const iframe = window.frameElement;
            if (iframe) {
                const iframeContainer = iframe.closest('div.element-container');
                let card = iframe.closest('div[data-testid="stVerticalBlockBorderWrapper"]');
                if (!card) {
                    card = iframe.closest('div[data-testid="stVerticalBlock"]');
                }
                
                if (card) {
                    // Make it look clickable
                    card.style.cursor = 'pointer';
                    
                    // Hide iframe's container to completely remove its vertical whitespace
                    if (iframeContainer) {
                        iframeContainer.style.display = 'none';
                    }
                    
                    // Prevent multiple listeners
                    if (!card.dataset.hasClickListener) {
                        card.dataset.hasClickListener = 'true';
                        card.addEventListener('click', function(e) {
                            // Allow clicking the actual checkbox or actual inputs if any exist inside
                            if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
                            
                            // Find our specific hidden button for this exact card
                            const btn = card.querySelector('button[kind="secondary"]');
                            if (btn) btn.click();
                        });
                        
                        // Hide the actual button's container to completely remove its vertical whitespace
                        const btns = card.querySelectorAll('button[kind="secondary"]');
                        btns.forEach(b => {
                            if (b.innerText.trim() === "Open") {
                                const btnContainer = b.closest('div.element-container');
                                if (btnContainer) {
                                    btnContainer.style.display = 'none';
                                }
                            }
                        });
                    }
                }
            }
            </script>
            """,
            height="content",
            width="content",
        )

        return clicked


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
        tiles.append(("Distance", f"{metrics.distance_km:.2f} km"))
    if metrics.avg_pace:
        tiles.append(("Avg pace", metrics.avg_pace))
    if metrics.avg_speed_kmh is not None:
        tiles.append(("Avg speed", f"{metrics.avg_speed_kmh:.1f} km/h"))
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


def render_route_map(polyline_str: Optional[str], *, height: int = 360) -> None:
    """Render a Strava route on an OSM basemap from an encoded polyline.

    Decodes ``polyline_str`` with the ``polyline`` library, drops the points
    onto a ``folium`` map, fits the viewport to the route, and embeds via
    ``streamlit-folium``. Silent no-op when the polyline is missing or
    contains fewer than two points.
    """
    if not polyline_str:
        return
    try:
        import polyline as _polyline
    except ImportError:
        return
    try:
        coords = _polyline.decode(polyline_str)
    except Exception:
        return
    if len(coords) < 2:
        return

    try:
        import folium
        from streamlit_folium import st_folium
    except ImportError:
        return

    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    center = (sum(lats) / len(lats), sum(lons) / len(lons))
    bounds = [(min(lats), min(lons)), (max(lats), max(lons))]

    fmap = folium.Map(location=center, tiles="OpenStreetMap", zoom_start=13)
    folium.PolyLine(coords, color="#fc4c02", weight=4, opacity=0.85).add_to(fmap)
    fmap.fit_bounds(bounds, padding=(20, 20))
    st_folium(fmap, height=height, width=None, returned_objects=[])


def render_photo_gallery(
    urls: list[str], *, columns: int = 3, width: int = 280
) -> None:
    """Render Strava-hosted photos in a small responsive thumbnail grid.

    Image URLs are passed straight to ``st.image`` so the browser fetches
    each one from Strava's CDN at view time — nothing is downloaded into
    the data repo. ``width`` caps each thumbnail so the gallery stays
    compact even on wide viewports. No-op when ``urls`` is empty.
    """
    if not urls:
        return
    cols = st.columns(min(columns, len(urls)))
    for i, url in enumerate(urls):
        with cols[i % len(cols)]:
            st.image(url, width=width)


def _format_lap_time(seconds: Optional[int]) -> str:
    if not seconds or seconds <= 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_lap_pace(distance_m: Optional[float], moving_s: Optional[int]) -> str:
    if not distance_m or not moving_s or distance_m <= 0 or moving_s <= 0:
        return "—"
    spk = moving_s / (distance_m / 1000.0)
    m, s = divmod(int(round(spk)), 60)
    return f"{m}:{s:02d}/km"


def render_lap_bars(laps: list[Lap]) -> None:
    """Bar chart: width = lap duration, height = speed (km/h).

    Variable widths mean the x-axis reads as cumulative time, so a long
    slow lap takes up more horizontal space than a quick one. Height is
    speed (km/h) — faster laps are taller, matching the user's "lower
    pace → taller bar" intuition. Hover shows pace, distance, and time.

    No-op when there are fewer than two laps with usable distance data.
    """
    valid: list[tuple[Lap, float, float, float]] = []
    cumulative_min = 0.0
    for lap in laps:
        duration_s = lap.moving_time_s or lap.elapsed_time_s
        if not duration_s or not lap.distance_m or lap.distance_m <= 0:
            continue
        duration_min = duration_s / 60.0
        speed_kmh = (lap.distance_m / 1000.0) / (duration_s / 3600.0)
        center = cumulative_min + duration_min / 2.0
        valid.append((lap, center, duration_min, speed_kmh))
        cumulative_min += duration_min

    if len(valid) < 2:
        return

    try:
        import plotly.graph_objects as go
    except ImportError:
        return

    hover_texts: list[str] = []
    for lap, _, duration_min, speed_kmh in valid:
        duration_s = lap.moving_time_s or lap.elapsed_time_s or 0
        pace_str = _format_lap_pace(lap.distance_m, duration_s)
        time_str = _format_lap_time(duration_s)
        hr_line = f"<br>Avg HR: {lap.avg_heart_rate} bpm" if lap.avg_heart_rate else ""
        assert lap.distance_m is not None
        hover_texts.append(
            f"Lap {lap.lap_index}<br>"
            f"Pace: {pace_str}<br>"
            f"Speed: {speed_kmh:.1f} km/h<br>"
            f"Distance: {lap.distance_m / 1000:.2f} km<br>"
            f"Time: {time_str}"
            f"{hr_line}"
        )

    st.markdown("**Lap pace**")
    fig = go.Figure(
        go.Bar(
            x=[v[1] for v in valid],
            y=[v[3] for v in valid],
            width=[v[2] for v in valid],
            hovertext=hover_texts,
            hoverinfo="text",
            marker_color="#fc4c02",
        )
    )
    fig.update_layout(
        height=260,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="cumulative time (min)",
        yaxis_title="speed (km/h)",
        bargap=0.02,
    )
    st.plotly_chart(fig, width="stretch")


def render_lap_table(laps: list[Lap]) -> None:
    """Render per-lap aggregates as a compact table.

    Shows lap #, time, distance, pace, avg HR, and elevation gain. Missing
    fields render as ``—``. No-op when ``laps`` is empty or all laps have
    zero duration (e.g. a manually started/stopped strength workout).
    """
    if not laps:
        return
    rows: list[dict[str, str]] = []
    for lap in laps:
        rows.append(
            {
                "Lap": str(lap.lap_index),
                "Time": _format_lap_time(lap.moving_time_s or lap.elapsed_time_s),
                "Distance": (
                    f"{lap.distance_m / 1000.0:.2f} km" if lap.distance_m else "—"
                ),
                "Pace": _format_lap_pace(
                    lap.distance_m, lap.moving_time_s or lap.elapsed_time_s
                ),
                "Avg HR": f"{lap.avg_heart_rate} bpm" if lap.avg_heart_rate else "—",
                "Elev. gain": (
                    f"{lap.elevation_gain_m:.0f} m"
                    if lap.elevation_gain_m is not None
                    else "—"
                ),
            }
        )
    if not rows:
        return
    st.markdown("**Laps**")
    st.table(rows)


def render_streams_charts(streams: dict[str, list[float]]) -> None:
    """Render HR and elevation time-series as Plotly line charts.

    ``streams`` is the dict returned by ``StravaClient.activity_streams`` —
    one key per stream type. We render heart-rate over time and altitude
    over distance (km) when both are present; either chart is skipped
    individually if its data isn't there.
    """
    if not streams:
        return
    time_s = streams.get("time") or []
    distance_m = streams.get("distance") or []
    hr = streams.get("heartrate") or []
    altitude = streams.get("altitude") or []
    if not (hr or altitude):
        return

    try:
        import plotly.graph_objects as go
    except ImportError:
        return

    col_hr, col_alt = st.columns(2)

    if hr and time_s and len(hr) == len(time_s):
        with col_hr:
            st.markdown("**Heart rate**")
            x_min = [t / 60.0 for t in time_s]
            fig = go.Figure(
                go.Scatter(x=x_min, y=hr, mode="lines", line=dict(color="#e63946"))
            )
            fig.update_layout(
                height=240,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title="time (min)",
                yaxis_title="bpm",
            )
            st.plotly_chart(fig, width="stretch")

    if altitude and distance_m and len(altitude) == len(distance_m):
        with col_alt:
            st.markdown("**Elevation**")
            x_km = [d / 1000.0 for d in distance_m]
            fig = go.Figure(
                go.Scatter(
                    x=x_km,
                    y=altitude,
                    mode="lines",
                    line=dict(color="#2a9d8f"),
                    fill="tozeroy",
                )
            )
            fig.update_layout(
                height=240,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title="distance (km)",
                yaxis_title="m",
            )
            st.plotly_chart(fig, width="stretch")


_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def render_plan_day(planned: PlannedActivity, *, key_prefix: str) -> Optional[bool]:
    """Render one planned-activity card with a completion checkbox.

    Returns the new ``completed`` value when the checkbox state changed
    versus ``planned.completed``, otherwise ``None``. ``key_prefix`` should
    uniquely identify the slot within the page (e.g. include the plan's
    week_start) so widget keys don't collide.
    """
    icon = sport_icon(planned.sport)
    header = format_date(planned.day)

    with st.container(border=True):
        st.caption(header)
        st.markdown(f"### {icon}  {planned.title}")
        chips: list[str] = []
        if planned.duration_minutes is not None:
            chips.append(f"{planned.duration_minutes} min")
        if planned.intensity:
            chips.append(f"intensity: {planned.intensity}")
        if chips:
            st.caption("  ·  ".join(chips))
        if planned.description:
            st.text(planned.description)
        new_value = st.checkbox(
            "Completed",
            value=planned.completed,
            key=f"{key_prefix}_done_{planned.day.isoformat()}",
        )
        if new_value != planned.completed:
            return new_value
    return None


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
