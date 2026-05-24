"""Streamlit entry point for the AI Sports Planner.

Run with::

    streamlit run src/ui/app.py

Streamlit auto-discovers files under ``src/ui/pages/`` and renders them
in the sidebar as additional pages.
"""

from __future__ import annotations

import sys
from pathlib import Path
import importlib

# Ensure the repository root is on sys.path so `from src...` imports work
repo_root = Path(__file__).resolve().parents[2]
repo_root_str = str(repo_root)
if repo_root_str not in sys.path:
    sys.path.insert(0, repo_root_str)

# Invalidate import caches to avoid stale package lookups in some runtimes
importlib.invalidate_caches()

import streamlit as st

from src.ui.auth import require_password


def main() -> None:
    st.set_page_config(
        page_title="AI Sports Planner",
        page_icon="🏃",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    require_password()

    pages = [
        st.Page("pages/1_Dashboard.py", title="Dashboard", icon="📊", default=True),
        st.Page("pages/2_Activity_Detail.py", title="Activity Detail", icon="🔍"),
        st.Page("pages/3_Weekly_Plan.py", title="Weekly Plan", icon="📅"),
        st.Page("pages/4_Profile.py", title="Profile", icon="👤"),
    ]

    pg = st.navigation(pages)
    pg.run()


main()
