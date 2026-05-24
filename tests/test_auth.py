"""Regression tests for the Streamlit password gate."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from src.config import get_settings

PASSWORD = "letmein"
APP = """
import streamlit as st

from src.ui.auth import require_password

require_password()
st.markdown("UNLOCKED_MARKER")
"""


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_DATA_REPO", "test/test-repo")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()


def test_password_gate_unlocks_after_submit() -> None:
    at = AppTest.from_string(APP).run()

    assert any("Password" in (widget.label or "") for widget in at.text_input)
    assert not any("UNLOCKED_MARKER" in str(item.value) for item in at.markdown)

    at.text_input[0].set_value(PASSWORD).run()
    at.button[0].click().run()

    assert not any("Password" in (widget.label or "") for widget in at.text_input)
    assert any("UNLOCKED_MARKER" in str(item.value) for item in at.markdown)
