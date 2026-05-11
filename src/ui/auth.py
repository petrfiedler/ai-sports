"""Single-password gate for the Streamlit app.

The whole app sits behind one shared password (read from
``Settings.app_password``). Each page must call :func:`require_password`
as its first statement so direct navigation cannot bypass the gate.
"""

from __future__ import annotations

from hmac import compare_digest

import streamlit as st

from src.config import get_settings

_AUTH_KEY = "authenticated"
_INPUT_KEY = "_password_input"


def _check_password() -> None:
    settings = get_settings()
    entered = st.session_state.get(_INPUT_KEY, "")
    if entered and compare_digest(entered, settings.app_password):
        st.session_state[_AUTH_KEY] = True
        st.session_state[_INPUT_KEY] = ""
    else:
        st.session_state[_AUTH_KEY] = False


def require_password() -> None:
    """Block the page until the correct app password is entered.

    On first load, renders a password input and ``st.stop()``s the
    script. After a correct entry, the session state flag is set and
    subsequent reruns flow through untouched.
    """
    if st.session_state.get(_AUTH_KEY):
        return

    st.title("AI Sports Planner")
    st.text_input(
        "Password",
        type="password",
        key=_INPUT_KEY,
        on_change=_check_password,
    )
    if st.session_state.get(_INPUT_KEY) and not st.session_state.get(_AUTH_KEY):
        st.error("Incorrect password.")
    st.stop()
