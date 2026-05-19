"""Streamlit entry point for the AI Sports Planner.

Run with::

    streamlit run src/ui/app.py

Streamlit auto-discovers files under ``src/ui/pages/`` and renders them
in the sidebar as additional pages.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.ui.auth import require_password


def main() -> None:
    st.set_page_config(
        page_title="AI Sports Planner",
        page_icon="🏃",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    require_password()

    st.title("AI Sports Planner")
    st.write(
        "Welcome. Open **Dashboard** from the sidebar to log a workout, "
        "**Activity Detail** to inspect or edit one, **Weekly Plan** to "
        "see your upcoming training week, or **Profile** to tell the "
        "planner about your goals."
    )


main()
