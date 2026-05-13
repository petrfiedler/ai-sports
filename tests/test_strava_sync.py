"""Tests for src.services.strava_sync — covers auth refresh and the two endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from src.services.strava_sync import StravaClient, StravaError, _pick_photo_url


@dataclass
class FakeResponse:
    status_code: int
    payload: Any
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self.payload


@dataclass
class FakeSession:
    """In-memory stand-in for ``requests.Session`` that records calls."""

    post_responses: list[FakeResponse] = field(default_factory=list)
    get_responses: dict[str, list[FakeResponse]] = field(default_factory=dict)
    posts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    gets: list[tuple[str, dict[str, Any], dict[str, Any]]] = field(default_factory=list)

    def post(self, url: str, data: dict[str, Any], timeout: int = 15) -> FakeResponse:
        self.posts.append((url, data))
        if not self.post_responses:
            raise AssertionError(f"No POST response queued for {url}")
        return self.post_responses.pop(0)

    def get(
        self,
        url: str,
        headers: dict[str, Any],
        params: Optional[dict[str, Any]] = None,
        timeout: int = 20,
    ) -> FakeResponse:
        self.gets.append((url, headers, params or {}))
        # Lookup by path suffix so callers can stub specific endpoints.
        for suffix, queue in self.get_responses.items():
            if url.endswith(suffix) and queue:
                return queue.pop(0)
        raise AssertionError(f"No GET response queued for {url}")


def _client(session: FakeSession, *, refresh_token: str = "rt-old") -> StravaClient:
    return StravaClient(
        client_id="cid",
        client_secret="cs",
        refresh_token=refresh_token,
        session=session,  # type: ignore[arg-type]
    )


def test_refresh_called_on_first_request_and_token_attached() -> None:
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(
            200,
            {
                "access_token": "tok-1",
                "refresh_token": "rt-new",
                "expires_at": time.time() + 3600,
            },
        )
    )
    session.get_responses["/athlete/activities"] = [FakeResponse(200, [])]
    client = _client(session)

    client.recent_activities(since=__import__("datetime").date(2026, 1, 1))

    assert len(session.posts) == 1, "refresh should happen exactly once"
    _, get_headers, _ = session.gets[0]
    assert get_headers["Authorization"] == "Bearer tok-1"


def test_refresh_not_repeated_while_token_fresh() -> None:
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(
            200,
            {"access_token": "tok-1", "refresh_token": "rt", "expires_at": time.time() + 3600},
        )
    )
    session.get_responses["/athlete/activities"] = [
        FakeResponse(200, []),
        FakeResponse(200, []),
    ]
    client = _client(session)
    from datetime import date

    client.recent_activities(since=date(2026, 1, 1))
    client.recent_activities(since=date(2026, 1, 1))

    assert len(session.posts) == 1


def test_refresh_failure_raises_strava_error() -> None:
    session = FakeSession()
    session.post_responses.append(FakeResponse(400, {"message": "bad"}, text="bad"))
    client = _client(session)
    from datetime import date

    with pytest.raises(StravaError):
        client.recent_activities(since=date(2026, 1, 1))


def test_recent_activities_pages_until_short_page() -> None:
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(
            200,
            {"access_token": "tok", "refresh_token": "rt", "expires_at": time.time() + 3600},
        )
    )
    # per_page defaults to 50; emulate a full first page + partial second.
    page1 = [{"id": i} for i in range(50)]
    page2 = [{"id": 50}, {"id": 51}]
    session.get_responses["/athlete/activities"] = [
        FakeResponse(200, page1),
        FakeResponse(200, page2),
    ]
    client = _client(session)
    from datetime import date

    out = client.recent_activities(since=date(2026, 1, 1))
    assert len(out) == 52
    assert len(session.gets) == 2


def test_activity_photos_returns_empty_on_error() -> None:
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(
            200,
            {"access_token": "tok", "refresh_token": "rt", "expires_at": time.time() + 3600},
        )
    )
    session.get_responses["/activities/123/photos"] = [FakeResponse(500, {}, text="boom")]
    client = _client(session)
    assert client.activity_photos(123) == []


def test_activity_photos_picks_urls() -> None:
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(
            200,
            {"access_token": "tok", "refresh_token": "rt", "expires_at": time.time() + 3600},
        )
    )
    session.get_responses["/activities/123/photos"] = [
        FakeResponse(
            200,
            [
                {"urls": {"600": "https://cdn/a-600.jpg", "1024": "https://cdn/a-1024.jpg"}},
                {"urls": {"256": "https://cdn/b-256.jpg"}},  # no 1024 → falls back to largest
                {"urls": {}},  # ignored
            ],
        )
    ]
    client = _client(session)
    urls = client.activity_photos(123, size=1024)
    assert urls == ["https://cdn/a-1024.jpg", "https://cdn/b-256.jpg"]


def test_pick_photo_url_handles_missing_urls() -> None:
    assert _pick_photo_url({}, 1024) is None
    assert _pick_photo_url({"urls": {}}, 1024) is None


def test_refresh_token_rotation_persists() -> None:
    """If Strava rotates the refresh token, the client must use the new one."""
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(
            200,
            {
                "access_token": "tok-1",
                "refresh_token": "rt-new",
                "expires_at": time.time() - 1,  # already expired → force second refresh
            },
        )
    )
    session.post_responses.append(
        FakeResponse(
            200,
            {"access_token": "tok-2", "refresh_token": "rt-newer", "expires_at": time.time() + 3600},
        )
    )
    session.get_responses["/athlete/activities"] = [
        FakeResponse(200, []),
        FakeResponse(200, []),
    ]
    client = _client(session, refresh_token="rt-old")
    from datetime import date

    client.recent_activities(since=date(2026, 1, 1))
    client.recent_activities(since=date(2026, 1, 1))

    assert len(session.posts) == 2
    # Second refresh must have sent the rotated token, not the original.
    assert session.posts[1][1]["refresh_token"] == "rt-new"
