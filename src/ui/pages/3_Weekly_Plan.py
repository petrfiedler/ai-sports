"""Weekly Plan page — view, refine, and tick off the AI-generated plan.

Stub for Phase 4; fleshed out in Phase 9.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from src.ui.auth import require_password
from src.ui.components import page_header

require_password()

page_header("Weekly Plan", "Generated training plan for the upcoming week (coming in Phase 9).")
st.info("Generate or view your weekly plan here once the Planner Agent is wired up.")
