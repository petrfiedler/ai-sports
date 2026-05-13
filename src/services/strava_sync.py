"""Strava API client.

Thin wrapper over the Strava v3 REST API. Uses a long-lived refresh token to
mint short-lived access tokens on demand. Only exposes the two endpoints the
sync agent needs: ``recent_activities`` and ``activity_photos``.

No business logic lives here — sport mapping, schema construction, and dedup
all happen in :mod:`src.agents.sync_agent`.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any, Optional

import requests

_TOKEN_URL = "https://www.strava.com/oauth/token"
_API_BASE = "https://www.strava.com/api/v3"
_TOKEN_REFRESH_MARGIN_S = 60


class StravaError(RuntimeError):
    """Raised when the Strava API returns an error or refresh fails."""


class StravaRateLimitError(StravaError):
    """Raised when Strava returns 429. Carries a usage hint when present."""

    def __init__(self, path: str, usage: str = "", limit: str = "") -> None:
        msg = f"Rate limited on {path}"
        if usage and limit:
            msg += f" (usage={usage}, limit={limit})"
        msg += ". Strava allows 600 req / 15 min and 6000 / day — wait a bit and retry."
        super().__init__(msg)


class StravaClient:
    """Strava REST client backed by a refresh token.

    Construct with the OAuth app credentials and a refresh token obtained
    once via :file:`scripts/strava_authorize.py`. Access tokens are minted
    lazily and reused until they're within a minute of expiry.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._session = session or requests.Session()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    # --- auth ----------------------------------------------------------

    def _refresh(self) -> None:
        resp = self._session.post(
            _TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            timeout=15,
        )
        if not resp.ok:
            raise StravaError(f"Token refresh failed: {resp.status_code} {resp.text}")
        payload = resp.json()
        self._access_token = payload["access_token"]
        self._expires_at = float(payload["expires_at"])
        # Strava may rotate the refresh token; keep the latest.
        new_refresh = payload.get("refresh_token")
        if new_refresh:
            self._refresh_token = new_refresh

    def _ensure_token(self) -> str:
        if self._access_token is None or time.time() >= self._expires_at - _TOKEN_REFRESH_MARGIN_S:
            self._refresh()
        assert self._access_token is not None
        return self._access_token

    # --- requests ------------------------------------------------------

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        token = self._ensure_token()
        resp = self._session.get(
            f"{_API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        )
        if resp.status_code == 429:
            raise StravaRateLimitError(
                path,
                usage=resp.headers.get("X-RateLimit-Usage", ""),
                limit=resp.headers.get("X-RateLimit-Limit", ""),
            )
        if not resp.ok:
            raise StravaError(f"GET {path} failed: {resp.status_code} {resp.text}")
        return resp.json()

    # --- endpoints -----------------------------------------------------

    def recent_activities(
        self, since: date, *, per_page: int = 50
    ) -> list[dict[str, Any]]:
        """Return summary objects for activities started on/after ``since``.

        Pages through the athlete activity list until an empty page or an
        activity older than ``since`` is encountered.
        """
        after = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            chunk = self._get(
                "/athlete/activities",
                params={"after": after, "page": page, "per_page": per_page},
            )
            if not isinstance(chunk, list) or not chunk:
                break
            out.extend(chunk)
            if len(chunk) < per_page:
                break
            page += 1
        return out

    def activity_photos(self, activity_id: int, *, size: int = 1024) -> list[str]:
        """Return photo URLs (largest variant per photo) for an activity.

        Returns an empty list when the activity has no photos or the
        endpoint declines (e.g. the activity is private to a non-owner).
        Rate-limit errors propagate so the caller can stop cleanly.
        """
        try:
            data = self._get(
                f"/activities/{activity_id}/photos",
                params={"size": size, "photo_sources": "true"},
            )
        except StravaRateLimitError:
            raise
        except StravaError:
            return []
        if not isinstance(data, list):
            return []
        urls: list[str] = []
        for photo in data:
            url = _pick_photo_url(photo, size)
            if url:
                urls.append(url)
        return urls

    def activity_detail(self, activity_id: int) -> dict[str, Any]:
        """Return the full detail object for an activity.

        The detail response includes fields absent from the list endpoint:
        ``description``, ``calories``, and embedded ``laps``. Returns an
        empty dict on a Strava error so callers can degrade gracefully.
        Rate-limit errors propagate so the caller can stop cleanly instead
        of treating the activity as having no description / laps.
        """
        try:
            data = self._get(f"/activities/{activity_id}", params={"include_all_efforts": "false"})
        except StravaRateLimitError:
            raise
        except StravaError:
            return {}
        return data if isinstance(data, dict) else {}

    def activity_streams(
        self, activity_id: int, *, keys: tuple[str, ...] = ("time", "heartrate", "altitude", "distance")
    ) -> dict[str, list[float]]:
        """Return time-series streams keyed by stream type.

        Strava returns each requested stream as an object with a ``data``
        list; we flatten that into ``{key: [values...]}``. Missing streams
        (e.g. no HR strap was worn) are simply absent from the result.
        Returns an empty dict on error.
        """
        try:
            data = self._get(
                f"/activities/{activity_id}/streams",
                params={"keys": ",".join(keys), "key_by_type": "true"},
            )
        except StravaError:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, list[float]] = {}
        for key, payload in data.items():
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                out[key] = list(payload["data"])
        return out


def _pick_photo_url(photo: dict[str, Any], requested_size: int) -> Optional[str]:
    """Pick the URL closest to ``requested_size`` from a Strava photo object."""
    urls = photo.get("urls")
    if not isinstance(urls, dict) or not urls:
        return None
    if str(requested_size) in urls:
        return urls[str(requested_size)]
    # Strava key is the longest edge in pixels; fall back to the largest.
    try:
        best_key = max(urls.keys(), key=lambda k: int(k))
    except (TypeError, ValueError):
        best_key = next(iter(urls))
    return urls[best_key]
