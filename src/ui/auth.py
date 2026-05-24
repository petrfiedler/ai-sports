"""Single-password gate for the Streamlit app.

The whole app sits behind one shared password (read from
``Settings.app_password``). Each page must call :func:`require_password`
as its first statement so direct navigation cannot bypass the gate.
"""

from __future__ import annotations

import time
from hmac import compare_digest

import streamlit as st

from src.config import get_settings

_AUTH_KEY = "authenticated"
_INPUT_KEY = "_password_input"
_COOKIE_KEY = "ai_sports_auth_session"
_COOKIE_EXPIRY_DAYS = 30


def _check_password(entered: str) -> bool:
    settings = get_settings()
    if entered and compare_digest(entered, settings.app_password):
        st.session_state[_AUTH_KEY] = True
        return True

    st.session_state[_AUTH_KEY] = False
    return False


def require_password() -> None:
    """Block the page until the correct app password is entered.

    On first load, renders a password input and ``st.stop()``s the
    script. After a correct entry, the session state flag is set and
    subsequent reruns flow through untouched.
    """
    if st.session_state.get(_AUTH_KEY):
        return

    # Check native cookie (Streamlit 1.40+)
    if hasattr(st, "context") and hasattr(st.context, "cookies"):
        if st.context.cookies.get(_COOKIE_KEY) == "true":
            st.session_state[_AUTH_KEY] = True
            return

    gate_container = st.empty()

    with gate_container.container():
        st.title("AI Sports Planner")
        with st.form("login_form"):
            st.info("Log in to access your planner.")
            # A dummy username field helps Firefox and other browsers recognize the login form to offer save-password
            # We inject it as raw HTML so it doesn't take up visual space in the UI
            st.markdown(
                '<input type="text" name="username" autocomplete="username" value="user" style="opacity: 0; position: absolute; z-index: -1;">',
                unsafe_allow_html=True,
            )
            entered_password = st.text_input(
                "Password",
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button("Log In")

    if submitted:
        if _check_password(entered_password):
            # Set cookie natively using JavaScript and trigger a hard page reload
            # A browser hard-reload instantly tells Firefox that a form submission resulted
            # in navigation, which is the strongest trigger for the "Save Password" prompt
            cookie_str = f"{_COOKIE_KEY}=true; max-age={_COOKIE_EXPIRY_DAYS * 24 * 60 * 60}; path=/;"
            js_code = f"""
                <script>
                    window.parent.document.cookie = "{cookie_str}";
                    window.parent.location.reload();
                </script>
            """
            st.iframe(js_code, height="content")

            # Immediately halt execution so the frontend can receive the JS block and navigate
            st.stop()
        else:
            with gate_container.container():
                st.error("Incorrect password.")

    st.stop()
