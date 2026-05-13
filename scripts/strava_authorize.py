"""One-shot Strava OAuth helper.

Run this locally **once** to obtain a long-lived refresh token, then paste
the printed value into ``.streamlit/secrets.toml`` as ``strava_refresh_token``.
Subsequent token refreshes happen automatically inside :class:`StravaClient`.

Usage:
    python scripts/strava_authorize.py <client_id> <client_secret>

What it does:
    1. Opens the Strava authorize URL in your browser.
    2. Spins up a tiny local HTTP server on port 8721 to catch the redirect.
    3. Exchanges the returned ``code`` for an access + refresh token pair.
    4. Prints the refresh token to stdout.

Before running, register a Strava API application at
https://www.strava.com/settings/api and set the "Authorization Callback Domain"
to ``localhost``.
"""

from __future__ import annotations

import http.server
import sys
import urllib.parse
import webbrowser
from typing import Optional

import requests

_REDIRECT_PORT = 8721
_REDIRECT_URI = f"http://localhost:{_REDIRECT_PORT}/callback"
_SCOPE = "read,activity:read_all"
_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
_TOKEN_URL = "https://www.strava.com/oauth/token"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: Optional[str] = None

    def do_GET(self) -> None:  # noqa: N802 — required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = (params.get("code") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if _CallbackHandler.code:
            self.wfile.write(b"Authorized. You can close this tab.")
        else:
            self.wfile.write(b"No code returned. Check the terminal for details.")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        # Suppress default access-log spam.
        return


def _capture_code(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": _REDIRECT_URI,
        "approval_prompt": "auto",
        "scope": _SCOPE,
    }
    url = f"{_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    print(f"Opening browser to: {url}")
    webbrowser.open(url)

    server = http.server.HTTPServer(("localhost", _REDIRECT_PORT), _CallbackHandler)
    try:
        server.handle_request()
    finally:
        server.server_close()
    if not _CallbackHandler.code:
        raise SystemExit("Authorization did not return a code.")
    return _CallbackHandler.code


def _exchange(client_id: str, client_secret: str, code: str) -> dict[str, object]:
    resp = requests.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: python scripts/strava_authorize.py <client_id> <client_secret>", file=sys.stderr)
        return 2
    client_id, client_secret = argv[1], argv[2]
    code = _capture_code(client_id)
    tokens = _exchange(client_id, client_secret, code)
    print("\nPaste into .streamlit/secrets.toml:")
    print(f'strava_client_id = "{client_id}"')
    print(f'strava_client_secret = "{client_secret}"')
    print(f'strava_refresh_token = "{tokens["refresh_token"]}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
