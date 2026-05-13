"""Tests for src.agents.sync_agent — exercises mapping, dedup, and metrics build-up."""

from __future__ import annotations

from typing import Any

import pytest

from src.agents.sync_agent import sync_recent
from src.models.schemas import ActivitySource, SportType
from src.services.storage import GitHubStorage
from src.services.strava_sync import StravaError, StravaRateLimitError
from tests.test_storage import FakeRepo  # reuse the in-memory repo


class FakeStravaClient:
    """Minimal stub matching StravaClient's surface used by sync_recent."""

    def __init__(
        self,
        activities: list[dict[str, Any]],
        photos: dict[int, list[str]] | None = None,
        details: dict[int, dict[str, Any]] | None = None,
        raise_on_recent: bool = False,
    ) -> None:
        self._activities = activities
        self._photos = photos or {}
        self._details = details or {}
        self._raise = raise_on_recent
        self.recent_calls: list[Any] = []
        self.photo_calls: list[int] = []
        self.detail_calls: list[int] = []

    def recent_activities(self, since: Any) -> list[dict[str, Any]]:
        self.recent_calls.append(since)
        if self._raise:
            raise StravaError("boom")
        return self._activities

    def activity_photos(self, activity_id: int, **_: Any) -> list[str]:
        self.photo_calls.append(activity_id)
        return self._photos.get(activity_id, [])

    def activity_detail(self, activity_id: int) -> dict[str, Any]:
        self.detail_calls.append(activity_id)
        extras = self._details.get(activity_id)
        if extras is None:
            return {}
        # Real Strava detail is a superset of the summary, so merge.
        summary = next((s for s in self._activities if s.get("id") == activity_id), {})
        return {**summary, **extras}


@pytest.fixture
def storage() -> GitHubStorage:
    return GitHubStorage(repo=FakeRepo())  # type: ignore[arg-type]


def _run_summary(activity_id: int, **overrides: Any) -> dict[str, Any]:
    base = {
        "id": activity_id,
        "name": "Morning run",
        "sport_type": "Run",
        "type": "Run",
        "start_date_local": "2026-05-11T07:30:00Z",
        "distance": 8200.0,  # metres
        "moving_time": 2400,  # seconds → 40 min
        "average_speed": 3.4,  # m/s
        "average_heartrate": 152.0,
        "max_heartrate": 178,
        "total_elevation_gain": 75.0,
        "map": {"summary_polyline": "abc123"},
        "total_photo_count": 0,
        "location_city": "Prague",
    }
    base.update(overrides)
    return base


def _detail(description: str = "", laps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"description": description, "laps": laps or []}


def test_sync_recent_imports_new_activity_with_metrics(
    storage: GitHubStorage,
) -> None:
    client = FakeStravaClient(activities=[_run_summary(111)])
    result = sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    assert len(result.imported) == 1
    assert result.skipped_existing == 0
    loaded = storage.load_activity(result.imported[0])
    assert loaded is not None
    activity, body = loaded
    assert activity.source == ActivitySource.STRAVA.value
    assert activity.sport == SportType.RUNNING.value
    assert activity.title == "Morning run"
    assert activity.duration_minutes == 40
    assert activity.location == "Prague"
    assert activity.metrics is not None
    assert activity.metrics.strava_id == 111
    assert activity.metrics.distance_km == pytest.approx(8.2)
    assert activity.metrics.avg_pace == "4:53/km"
    assert activity.metrics.avg_heart_rate == 152
    assert activity.metrics.map_polyline == "abc123"
    assert activity.metrics.photo_urls == []
    assert body.strip() == "Synced from Strava."
    assert client.detail_calls == [111]


def test_sync_recent_pulls_description_and_laps_from_detail(
    storage: GitHubStorage,
) -> None:
    summary = _run_summary(777)
    laps_payload = [
        {
            "lap_index": 1,
            "elapsed_time": 300,
            "moving_time": 295,
            "distance": 1000.0,
            "average_heartrate": 145.0,
            "max_heartrate": 158,
            "average_speed": 3.4,
            "total_elevation_gain": 5.0,
        },
        {
            "lap_index": 2,
            "elapsed_time": 320,
            "moving_time": 318,
            "distance": 1000.0,
            "average_heartrate": 150.0,
            "max_heartrate": 162,
            "average_speed": 3.1,
            "total_elevation_gain": 8.0,
        },
    ]
    details = {777: _detail(description="Felt strong on the climbs.", laps=laps_payload)}
    client = FakeStravaClient(activities=[summary], details=details)

    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.summary == "Felt strong on the climbs."
    assert activity.metrics is not None
    assert len(activity.metrics.laps) == 2
    lap1 = activity.metrics.laps[0]
    assert lap1.lap_index == 1
    assert lap1.moving_time_s == 295
    assert lap1.avg_heart_rate == 145
    assert lap1.elevation_gain_m == 5.0


def test_sync_recent_truncates_long_description_into_summary(
    storage: GitHubStorage,
) -> None:
    long_desc = "x" * 700
    details = {888: _detail(description=long_desc)}
    client = FakeStravaClient(activities=[_run_summary(888)], details=details)

    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    # Summary is capped at ACTIVITY_SUMMARY_MAX (500); notes preserves the full
    # description for the detail page.
    assert activity.summary is not None
    assert len(activity.summary) <= 500
    assert activity.summary.endswith("…")
    assert activity.notes == long_desc


def test_sync_recent_fetches_photos_only_when_count_positive(
    storage: GitHubStorage,
) -> None:
    summary = _run_summary(222, total_photo_count=2)
    photos = {222: ["https://cdn/x.jpg", "https://cdn/y.jpg"]}
    client = FakeStravaClient(activities=[summary], photos=photos)

    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    assert client.photo_calls == [222]
    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.metrics is not None
    assert activity.metrics.photo_urls == ["https://cdn/x.jpg", "https://cdn/y.jpg"]


def test_sync_recent_skips_photo_fetch_when_no_photos(
    storage: GitHubStorage,
) -> None:
    client = FakeStravaClient(activities=[_run_summary(333, total_photo_count=0)])
    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]
    assert client.photo_calls == []


def test_sync_recent_dedups_by_strava_id(storage: GitHubStorage) -> None:
    client = FakeStravaClient(activities=[_run_summary(444)])
    first = sync_recent(client=client, storage=storage)  # type: ignore[arg-type]
    assert len(first.imported) == 1

    # Second call with the same activity must dedup, not double-import.
    second = sync_recent(client=client, storage=storage)  # type: ignore[arg-type]
    assert second.imported == []
    assert second.skipped_existing == 1


class _RateLimitedClient:
    """Stub that raises ``StravaRateLimitError`` on the Nth detail call.

    Mirrors the real-world failure mode: list works, first few details work,
    then the 15-minute budget expires mid-loop and every subsequent detail
    call returns 429.
    """

    def __init__(self, activities: list[dict[str, Any]], rate_limit_after: int) -> None:
        self._activities = activities
        self._rate_limit_after = rate_limit_after
        self.detail_calls = 0

    def recent_activities(self, since: Any) -> list[dict[str, Any]]:
        return self._activities

    def activity_photos(self, activity_id: int, **_: Any) -> list[str]:
        return []

    def activity_detail(self, activity_id: int) -> dict[str, Any]:
        self.detail_calls += 1
        if self.detail_calls > self._rate_limit_after:
            raise StravaRateLimitError(f"/activities/{activity_id}", usage="600", limit="600")
        summary = next((s for s in self._activities if s.get("id") == activity_id), {})
        return {**summary, "description": "filled in by detail"}


def test_sync_stops_cleanly_on_rate_limit(storage: GitHubStorage) -> None:
    """A 429 mid-loop must surface as ``rate_limited=True`` instead of letting
    subsequent activities get stored with empty descriptions."""
    summaries = [_run_summary(i, start_date_local=f"2026-0{(i % 9) + 1}-01T07:30:00Z") for i in range(1, 6)]
    client = _RateLimitedClient(activities=summaries, rate_limit_after=2)
    result = sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    assert result.rate_limited is True
    # First two imports succeeded before the limit, the third triggered it,
    # the remaining two never got attempted.
    assert len(result.imported) == 2
    assert result.errors and "Rate limited" in result.errors[0]
    # Surviving imports must have their description from detail, not a
    # silently-missed null.
    for path in result.imported:
        loaded = storage.load_activity(path)
        assert loaded is not None
        activity, _ = loaded
        assert activity.summary == "filled in by detail"


def test_sync_recent_collects_strava_error(storage: GitHubStorage) -> None:
    client = FakeStravaClient(activities=[], raise_on_recent=True)
    result = sync_recent(client=client, storage=storage)  # type: ignore[arg-type]
    assert result.imported == []
    assert result.errors and "boom" in result.errors[0]


def test_sport_mapping_unknown_falls_through_to_other(storage: GitHubStorage) -> None:
    client = FakeStravaClient(activities=[_run_summary(555, sport_type="AlpineSki", type="AlpineSki")])
    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]
    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.sport == SportType.OTHER.value


def test_sport_mapping_picks_strava_specific_types(storage: GitHubStorage) -> None:
    client = FakeStravaClient(
        activities=[_run_summary(666, sport_type="GravelRide", type="Ride", name="Gravel loop")]
    )
    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]
    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.sport == SportType.CYCLING.value


def test_sync_uses_full_lookback_not_latest_stored_date(
    storage: GitHubStorage,
) -> None:
    """After an old activity is stored, a re-sync must still scan the full
    lookback — otherwise we'd never pick up activities older than what we
    already have.
    """
    from datetime import date, timedelta

    # Stage 1: a stored activity from 30 days ago.
    summary_recent = _run_summary(111, start_date_local="2026-04-13T07:30:00Z")
    sync_recent(  # type: ignore[arg-type]
        client=FakeStravaClient(activities=[summary_recent]),
        storage=storage,
    )

    # Stage 2: Strava returns the same recent activity AND an older one.
    summary_old = _run_summary(222, start_date_local="2025-08-01T07:30:00Z")
    client = FakeStravaClient(activities=[summary_recent, summary_old])
    today = date.today()
    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    # The `since` we passed Strava must be the full 10-year window, not
    # one day before the latest stored activity.
    last_since = client.recent_calls[-1]
    assert last_since <= today - timedelta(days=365 * 9), (
        f"Expected ~10-year lookback, got since={last_since}"
    )

    # And the older activity must now be stored.
    paths = storage.list_activities()
    assert any("2025-08-01" in p for p in paths)


def test_sync_refreshes_stale_strava_activities(storage: GitHubStorage) -> None:
    """Pre-existing Strava activities missing description/location/laps should
    get backfilled when the user clicks Sync again, without losing any
    user-edited fields.
    """
    # First sync: no detail data wired, so summary/laps/location stay empty.
    summary = _run_summary(444)
    client_v1 = FakeStravaClient(activities=[summary])  # no details
    sync_recent(client=client_v1, storage=storage)  # type: ignore[arg-type]

    path = storage.list_activities()[0]
    loaded = storage.load_activity(path)
    assert loaded is not None
    stale, _ = loaded
    assert stale.summary is None
    assert stale.metrics is not None and not stale.metrics.laps

    # Simulate a user edit: bump RPE via the reviser. This must survive refresh.
    stale.rpe = 7
    storage.update_activity(path, stale, "Synced from Strava.")

    # Second sync: same summary, but now Strava returns rich detail.
    detail = _detail(
        description="Hard tempo effort.",
        laps=[
            {
                "lap_index": 1,
                "elapsed_time": 300,
                "moving_time": 295,
                "distance": 1000.0,
                "average_heartrate": 165.0,
                "total_elevation_gain": 3.0,
            }
        ],
    )
    client_v2 = FakeStravaClient(activities=[summary], details={444: detail})
    result = sync_recent(client=client_v2, storage=storage)  # type: ignore[arg-type]

    assert result.imported == []  # nothing new
    assert result.skipped_existing == 1
    assert len(result.refreshed) == 1

    refreshed = storage.load_activity(path)
    assert refreshed is not None
    refreshed_activity, _ = refreshed
    assert refreshed_activity.summary == "Hard tempo effort."
    assert refreshed_activity.location == "Prague"
    assert refreshed_activity.metrics is not None
    assert len(refreshed_activity.metrics.laps) == 1
    # User-edited RPE survived the refresh.
    assert refreshed_activity.rpe == 7


def test_location_falls_back_to_timezone_when_city_missing(
    storage: GitHubStorage,
) -> None:
    """Strava deprecated ``location_city``; we must parse the timezone instead."""
    summary = _run_summary(
        900,
        location_city=None,  # what real Strava returns nowadays
        timezone="(GMT+01:00) Europe/Prague",
    )
    client = FakeStravaClient(activities=[summary])
    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.location == "Prague"


def test_location_handles_compound_city_names(storage: GitHubStorage) -> None:
    """Underscore-separated city names ('New_York') should become 'New York'."""
    summary = _run_summary(
        901,
        location_city=None,
        timezone="(GMT-05:00) America/New_York",
    )
    sync_recent(  # type: ignore[arg-type]
        client=FakeStravaClient(activities=[summary]),
        storage=storage,
    )
    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.location == "New York"


def test_splits_substitute_when_only_one_lap(storage: GitHubStorage) -> None:
    """A single-lap activity should fall back to ``splits_metric`` for chart data."""
    summary = _run_summary(1000)
    splits = [
        {
            "split": 1,
            "distance": 1001.0,
            "elapsed_time": 350,
            "moving_time": 348,
            "average_speed": 2.87,
            "average_heartrate": 145,
            "elevation_difference": 5.0,
        },
        {
            "split": 2,
            "distance": 1000.5,
            "elapsed_time": 360,
            "moving_time": 358,
            "average_speed": 2.79,
            "average_heartrate": 152,
            "elevation_difference": 3.0,
        },
        {
            "split": 3,
            "distance": 998.0,
            "elapsed_time": 345,
            "moving_time": 343,
            "average_speed": 2.91,
            "average_heartrate": 149,
            "elevation_difference": -2.0,
        },
    ]
    single_lap = [
        {
            "lap_index": 1,
            "elapsed_time": 1055,
            "moving_time": 1049,
            "distance": 2999.5,
            "average_heartrate": 148.0,
            "average_speed": 2.86,
            "total_elevation_gain": 6.0,
        }
    ]
    detail = {"description": "", "laps": single_lap, "splits_metric": splits}
    client = FakeStravaClient(activities=[summary], details={1000: detail})

    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.metrics is not None
    # Splits replaced the lone auto-lap.
    assert len(activity.metrics.laps) == 3
    assert activity.metrics.laps[0].distance_m == pytest.approx(1001.0)
    assert activity.metrics.laps[1].avg_heart_rate == 152


def test_splits_ignored_when_real_laps_exist(storage: GitHubStorage) -> None:
    """If Strava already gave us multiple user-level laps, splits stay unused."""
    summary = _run_summary(1001)
    real_laps = [
        {
            "lap_index": 1,
            "elapsed_time": 300,
            "moving_time": 295,
            "distance": 1000.0,
            "average_heartrate": 145.0,
            "average_speed": 3.4,
            "total_elevation_gain": 5.0,
        },
        {
            "lap_index": 2,
            "elapsed_time": 305,
            "moving_time": 300,
            "distance": 1000.0,
            "average_heartrate": 150.0,
            "average_speed": 3.3,
            "total_elevation_gain": 7.0,
        },
    ]
    splits = [
        {"split": 1, "distance": 1001.0, "moving_time": 350, "average_speed": 2.87},
        {"split": 2, "distance": 1000.5, "moving_time": 360, "average_speed": 2.79},
    ]
    detail = {"description": "", "laps": real_laps, "splits_metric": splits}
    client = FakeStravaClient(activities=[summary], details={1001: detail})

    sync_recent(client=client, storage=storage)  # type: ignore[arg-type]

    loaded = storage.load_activity(storage.list_activities()[0])
    assert loaded is not None
    activity, _ = loaded
    assert activity.metrics is not None
    # Real laps kept; speed of first lap confirms it's the user-level data.
    assert len(activity.metrics.laps) == 2
    assert activity.metrics.laps[0].avg_speed_ms == pytest.approx(3.4)


def test_refresh_picks_up_splits_for_previously_single_lap_activities(
    storage: GitHubStorage,
) -> None:
    """An activity stored with only 1 lap (under old code) should be re-refreshed
    once splits become available in the detail response."""
    summary = _run_summary(1100, timezone="(GMT+01:00) Europe/Prague")
    # Stage 1: legacy state — one auto-lap, no splits, no description, no
    # location (simulating an activity stored before any of these features
    # existed).
    legacy_detail = {
        "description": "",
        "laps": [
            {
                "lap_index": 1,
                "elapsed_time": 1200,
                "moving_time": 1190,
                "distance": 3000.0,
            }
        ],
    }
    client_v1 = FakeStravaClient(activities=[summary], details={1100: legacy_detail})
    sync_recent(client=client_v1, storage=storage)  # type: ignore[arg-type]

    path = storage.list_activities()[0]
    loaded = storage.load_activity(path)
    assert loaded is not None
    initial, _ = loaded
    assert initial.metrics is not None
    assert len(initial.metrics.laps) == 1

    # Strip the timezone-derived location to truly simulate legacy state.
    initial.location = None
    storage.update_activity(path, initial, "Synced from Strava.")

    # Stage 2: same activity but detail now exposes splits + description.
    rich_detail = {
        "description": "Tempo session.",
        "laps": legacy_detail["laps"],
        "splits_metric": [
            {"split": 1, "distance": 1000.0, "moving_time": 390, "average_speed": 2.56},
            {"split": 2, "distance": 1000.0, "moving_time": 400, "average_speed": 2.50},
            {"split": 3, "distance": 1000.0, "moving_time": 400, "average_speed": 2.50},
        ],
    }
    client_v2 = FakeStravaClient(activities=[summary], details={1100: rich_detail})
    result = sync_recent(client=client_v2, storage=storage)  # type: ignore[arg-type]

    assert result.imported == []
    assert len(result.refreshed) == 1
    refreshed = storage.load_activity(path)
    assert refreshed is not None
    refreshed_activity, _ = refreshed
    assert refreshed_activity.summary == "Tempo session."
    assert refreshed_activity.location == "Prague"
    assert refreshed_activity.metrics is not None
    assert len(refreshed_activity.metrics.laps) == 3


def test_refresh_skips_activities_with_existing_summary(
    storage: GitHubStorage,
) -> None:
    """If summary/location/laps are already populated, the refresh pass must
    not touch the activity (no extra detail call, no rewrite)."""
    # First sync WITH detail so the activity comes in non-stale.
    detail = _detail(description="Initial description.")
    client_v1 = FakeStravaClient(activities=[_run_summary(555)], details={555: detail})
    sync_recent(client=client_v1, storage=storage)  # type: ignore[arg-type]

    # Second sync: detail map intentionally empty. If the refresh pass ran on
    # this activity, it'd erase the summary; since the activity is non-stale,
    # it must be skipped instead.
    client_v2 = FakeStravaClient(activities=[_run_summary(555)])  # no details
    initial_detail_calls = len(client_v2.detail_calls)
    sync_recent(client=client_v2, storage=storage)  # type: ignore[arg-type]

    # Refresh pass made zero detail calls (everything was either dedup'd or non-stale).
    assert len(client_v2.detail_calls) == initial_detail_calls

    refreshed = storage.load_activity(storage.list_activities()[0])
    assert refreshed is not None
    activity, _ = refreshed
    assert activity.summary == "Initial description."
