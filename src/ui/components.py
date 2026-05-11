"""Reusable Streamlit UI components.

Empty placeholders for now — fleshed out in later phases:
- Phase 5 adds ``activity_card`` and ``follow_up_panel``.
- Phase 6 adds ``render_strength_table``, ``render_endurance_charts``,
  ``render_followups``.
- Phase 9 adds ``render_plan_day``.
"""

from __future__ import annotations

import streamlit as st


def page_header(title: str, subtitle: str | None = None) -> None:
    """Render a consistent page header across pages."""
    st.header(title)
    if subtitle:
        st.caption(subtitle)
