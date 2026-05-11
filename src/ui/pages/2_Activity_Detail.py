"""Activity Detail page — view, edit, and revise a single activity.

Stub for Phase 4; fleshed out in Phase 6.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from src.ui.auth import require_password
from src.ui.components import page_header

require_password()

page_header("Activity Detail", "Activity view, follow-ups, and revisions (coming in Phase 6).")
st.info("Open an activity from the Dashboard to see its details here.")
