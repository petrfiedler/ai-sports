"""Dashboard page — Quick Add and activity list.

Stub for Phase 4; fleshed out in Phase 5.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from src.ui.auth import require_password
from src.ui.components import page_header

require_password()

page_header("Dashboard", "Quick Add and recent activities (coming in Phase 5).")
st.info("Quick Add and the activity list will appear here.")
