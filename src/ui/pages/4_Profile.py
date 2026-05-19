"""Profile page — edit goals, preferred sports, constraints, narrative.

The profile feeds the Planner Agent, so non-empty narrative + clear goals
produce noticeably better plans. Stored as ``profile.md`` in the data repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from src.models.schemas import ProfileSchema, SportType
from src.ui import services as ui_services
from src.ui.auth import require_password
from src.ui.components import page_header

require_password()

page_header("Profile", "Tell the planner who you are and what you want.")

try:
    current = ui_services.load_profile()
except Exception as exc:
    st.error(f"Could not load profile: {exc}")
    current = None

if current is None:
    st.info(
        "No profile yet. Fill in the form below — the more context you give, "
        "the better the AI plans will be."
    )
    current = ProfileSchema()

_SPORT_OPTIONS = [s.value for s in SportType]
_current_sports = [
    s if isinstance(s, str) else s.value for s in current.preferred_sports
]

with st.form("profile_form"):
    name = st.text_input("Name (optional)", value=current.name or "")

    goals_text = st.text_area(
        "Goals (one per line)",
        value="\n".join(current.goals),
        height=100,
        placeholder="e.g.\nHalf marathon under 2h\nBoulder V6 outdoors",
    )

    preferred_sports = st.multiselect(
        "Preferred sports",
        options=_SPORT_OPTIONS,
        default=[s for s in _current_sports if s in _SPORT_OPTIONS],
    )

    weekly_hours = st.number_input(
        "Weekly target hours (0 = no target)",
        min_value=0.0,
        max_value=40.0,
        value=float(current.weekly_target_hours or 0.0),
        step=0.5,
    )

    constraints_text = st.text_area(
        "Constraints (one per line)",
        value="\n".join(current.constraints),
        height=100,
        placeholder="e.g.\nNo gym on Tuesdays\nKnee injury — no jumping",
    )

    narrative = st.text_area(
        "Narrative (free-form description for the planner)",
        value=current.narrative or "",
        height=200,
        placeholder=(
            "Background, training history, what's working, what's not. "
            "The planner reads this verbatim, so write to your future coach."
        ),
    )

    submitted = st.form_submit_button("Save profile", type="primary")

if submitted:
    goals = [g.strip() for g in goals_text.splitlines() if g.strip()]
    constraints = [c.strip() for c in constraints_text.splitlines() if c.strip()]
    try:
        profile = ProfileSchema(
            name=name.strip() or None,
            goals=goals,
            preferred_sports=[SportType(s) for s in preferred_sports],
            weekly_target_hours=weekly_hours if weekly_hours > 0 else None,
            constraints=constraints,
            narrative=narrative.strip() or None,
        )
    except Exception as exc:
        st.error(f"Invalid profile: {exc}")
    else:
        try:
            with st.spinner("Saving..."):
                ui_services.get_storage().save_profile(profile)
        except Exception as exc:
            st.error(f"Could not save profile: {exc}")
        else:
            ui_services.clear_profile_cache()
            st.success("Profile saved.")
            st.rerun()
