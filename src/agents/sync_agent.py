"""Sync Agent — pulls activities from Strava into the data repo.

Stays deliberately thin: a stateless function that, given a ``StravaClient``
and a ``GitHubStorage``, walks the recent Strava feed, maps each summary into
an ``ActivitySchema``, dedups by ``metrics.strava_id``, and commits.

Map polylines and photo URLs are stored as references only — image bytes and
tile data live on Strava/OSM and are loaded by the browser at view time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from src.models.schemas import (
    ACTIVITY_SUMMARY_MAX,
    ActivitySchema,
    ActivitySource,
    EnduranceMetrics,
    Intensity,
    Lap,
    SportType,
)
from src.services.storage import GitHubStorage
from src.services.strava_sync import StravaClient, StravaError, StravaRateLimitError
from src.agents.parser_agent import revise_activity

# Initial sync should cover the full history; subsequent syncs short-circuit
# via the dedup set so this only matters once per athlete.
_DEFAULT_LOOKBACK_DAYS = 365 * 10

# Strava sport_type / type → our SportType. Strava's `sport_type` is more
# specific than `type` (e.g. "TrailRun" vs "Run"); we accept either.
_SPORT_MAP: dict[str, SportType] = {
    "Run": SportType.RUNNING,
    "TrailRun": SportType.RUNNING,
    "VirtualRun": SportType.RUNNING,
    "Ride": SportType.CYCLING,
    "VirtualRide": SportType.CYCLING,
    "GravelRide": SportType.CYCLING,
    "MountainBikeRide": SportType.CYCLING,
    "EBikeRide": SportType.CYCLING,
    "Swim": SportType.SWIMMING,
    "Hike": SportType.HIKING,
    "Walk": SportType.WALKING,
    "WeightTraining": SportType.STRENGTH,
    "Workout": SportType.STRENGTH,
    "Yoga": SportType.YOGA,
    "RockClimbing": SportType.CLIMBING,
}


@dataclass
class SyncResult:
    """Outcome of a single :func:`sync_recent` call."""

    imported: list[str] = field(default_factory=list)
    skipped_existing: int = 0
    refreshed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rate_limited: bool = False


def _map_sport(activity: dict[str, Any]) -> SportType:
    raw = activity.get("sport_type") or activity.get("type") or ""
    return _SPORT_MAP.get(raw, SportType.OTHER)


def _format_pace(seconds_per_km: Optional[float]) -> Optional[str]:
    if not seconds_per_km or seconds_per_km <= 0:
        return None
    total = int(round(seconds_per_km))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}/km"


def _pace_from_summary(summary: dict[str, Any]) -> Optional[str]:
    distance_m = summary.get("distance") or 0
    moving_time_s = summary.get("moving_time") or 0
    if distance_m <= 0 or moving_time_s <= 0:
        return None
    seconds_per_km = moving_time_s / (distance_m / 1000.0)
    return _format_pace(seconds_per_km)


def _intensity_from_hr(avg_hr: Optional[float]) -> Optional[Intensity]:
    """Rough heuristic so endurance entries get an intensity chip in the UI."""
    if not avg_hr:
        return None
    if avg_hr < 130:
        return Intensity.LOW
    if avg_hr < 160:
        return Intensity.MEDIUM
    return Intensity.HIGH


def _map_laps(raw_laps: Any) -> list[Lap]:
    """Build :class:`Lap` instances from Strava's embedded laps array."""
    if not isinstance(raw_laps, list):
        return []
    out: list[Lap] = []
    for i, raw in enumerate(raw_laps, start=1):
        if not isinstance(raw, dict):
            continue
        try:
            out.append(
                Lap(
                    lap_index=int(raw.get("lap_index", i)),
                    elapsed_time_s=int(raw.get("elapsed_time") or 0),
                    moving_time_s=(
                        int(raw["moving_time"]) if raw.get("moving_time") else None
                    ),
                    distance_m=(
                        float(raw["distance"]) if raw.get("distance") else None
                    ),
                    avg_heart_rate=(
                        int(raw["average_heartrate"])
                        if raw.get("average_heartrate")
                        else None
                    ),
                    max_heart_rate=(
                        int(raw["max_heartrate"]) if raw.get("max_heartrate") else None
                    ),
                    avg_speed_ms=(
                        float(raw["average_speed"])
                        if raw.get("average_speed")
                        else None
                    ),
                    elevation_gain_m=raw.get("total_elevation_gain"),
                )
            )
        except Exception:
            continue
    return out


def _map_splits(raw_splits: Any) -> list[Lap]:
    """Build :class:`Lap` instances from Strava's ``splits_metric`` array.

    Used as a fallback when the activity has 0 or 1 user-level laps but
    Strava still computed per-kilometre splits (most runs / rides).
    """
    if not isinstance(raw_splits, list):
        return []
    out: list[Lap] = []
    for raw in raw_splits:
        if not isinstance(raw, dict):
            continue
        moving = raw.get("moving_time") or 0
        if moving <= 0:
            continue
        try:
            out.append(
                Lap(
                    lap_index=int(raw.get("split") or len(out) + 1),
                    elapsed_time_s=int(raw.get("elapsed_time") or moving),
                    moving_time_s=int(moving),
                    distance_m=float(raw["distance"]) if raw.get("distance") else None,
                    avg_heart_rate=(
                        int(raw["average_heartrate"])
                        if raw.get("average_heartrate")
                        else None
                    ),
                    avg_speed_ms=(
                        float(raw["average_speed"])
                        if raw.get("average_speed")
                        else None
                    ),
                    elevation_gain_m=raw.get("elevation_difference"),
                )
            )
        except Exception:
            continue
    return out


def _location_from_strava(data: dict[str, Any]) -> Optional[str]:
    """Best-effort city label from a Strava activity object.

    Strava deprecated ``location_city`` (returns null on every activity since
    2019-ish). We fall back to parsing the city out of the ``timezone``
    string — e.g. ``"(GMT+01:00) Europe/Prague"`` → ``"Prague"``.
    """
    city = (data.get("location_city") or "").strip()
    if city:
        return city
    tz = (data.get("timezone") or "").strip()
    if "/" in tz:
        candidate = tz.rsplit("/", 1)[-1].replace("_", " ").strip()
        return candidate or None
    return None


def _truncate(text: str, limit: int = ACTIVITY_SUMMARY_MAX) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _build_metrics(
    summary: dict[str, Any],
    photo_urls: list[str],
    detail: Optional[dict[str, Any]] = None,
) -> EnduranceMetrics:
    src = {**summary, **(detail or {})}
    distance_m = src.get("distance")
    distance_km = (distance_m / 1000.0) if distance_m else None
    avg_speed = src.get("average_speed")
    avg_speed_kmh = (avg_speed * 3.6) if avg_speed else None
    map_obj = src.get("map") or {}
    polyline = map_obj.get("summary_polyline") or None
    laps = _map_laps(src.get("laps")) if detail else []
    # Strava activities often have only a single auto-lap (the whole activity).
    # In that case we substitute the 1-km splits so the bar chart has structure.
    if detail and len(laps) <= 1:
        splits = _map_splits(src.get("splits_metric"))
        if len(splits) > 1:
            laps = splits
    return EnduranceMetrics(
        distance_km=distance_km,
        avg_pace=_pace_from_summary(src),
        avg_speed_kmh=avg_speed_kmh,
        avg_heart_rate=(
            int(src["average_heartrate"]) if src.get("average_heartrate") else None
        ),
        max_heart_rate=int(src["max_heartrate"]) if src.get("max_heartrate") else None,
        elevation_gain_m=src.get("total_elevation_gain"),
        calories=int(src["calories"]) if src.get("calories") else None,
        strava_id=src.get("id"),
        map_polyline=polyline,
        photo_urls=photo_urls,
        laps=laps,
    )


def _activity_from_summary(
    summary: dict[str, Any],
    photo_urls: list[str],
    detail: Optional[dict[str, Any]] = None,
) -> ActivitySchema:
    sport = _map_sport(summary)
    start_iso = summary.get("start_date_local") or summary.get("start_date") or ""
    activity_date = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).date()
    duration_minutes = max(1, int(round((summary.get("moving_time") or 0) / 60.0)))
    title = (summary.get("name") or sport.value.title()).strip() or sport.value.title()
    metrics = _build_metrics(summary, photo_urls, detail)
    description = ""
    if detail:
        description = (detail.get("description") or "").strip()
    location = _location_from_strava({**summary, **(detail or {})})
    return ActivitySchema(
        title=title,
        sport=sport,
        activity_date=activity_date,
        duration_minutes=duration_minutes,
        source=ActivitySource.STRAVA,
        intensity=_intensity_from_hr(summary.get("average_heartrate")),
        location=location,
        summary=_truncate(description) if description else None,
        notes=(
            description
            if description and len(description) > ACTIVITY_SUMMARY_MAX
            else None
        ),
        metrics=metrics,
    )


def _enhance_with_llm(activity: ActivitySchema, description: str) -> ActivitySchema:
    """Passes the drafted activity and raw description to the parser to extract exercises & sets."""
    if not description:
        return activity

    instruction = (
        "Extract any structured data (especially strength exercises, sets, reps, lengths, weights) "
        "from the following Strava description and add it to the activity's exercises list. "
        "Keep the existing core metrics (sport, duration, distance, date) EXACTLY as they are. "
        f"Description: {description}"
    )

    result = revise_activity(activity, instruction, today=activity.activity_date)
    return result.activity or activity


def _existing_strava_ids(storage: GitHubStorage) -> set[int]:
    """Read all stored activities once and collect their Strava IDs."""
    ids: set[int] = set()
    for path in storage.list_activities():
        try:
            loaded = storage.load_activity(path)
        except Exception:
            continue
        if loaded is None:
            continue
        activity, _ = loaded
        if activity.metrics and activity.metrics.strava_id:
            ids.add(activity.metrics.strava_id)
    return ids


def _is_stale(activity: ActivitySchema) -> bool:
    """A Strava activity is 'stale' when it could still benefit from a fresh
    detail call.

    Three signals make an activity look 'detail-fetched and complete':
    - it has a non-empty ``location`` (we always populate this now via the
      timezone fallback, so missing location → never refreshed under the new
      code),
    - it has a multi-entry ``laps`` array (≥2 — single auto-laps that
      pre-date the splits fallback still look stale),
    - or it has a stored ``summary`` (the Strava description, when one
      exists).

    Activities whose Strava data genuinely has nothing more to offer
    (treadmill walks, etc.) trip the detail call every sync, but the
    before/after comparison in :func:`_refresh_stale_activities` prevents
    any commits.
    """
    if activity.source != ActivitySource.STRAVA.value:
        return False
    has_location = bool(activity.location)
    has_lap_structure = bool(activity.metrics and len(activity.metrics.laps) >= 2)
    has_summary = bool(activity.summary)
    if has_location and (has_lap_structure or has_summary):
        return False
    return True


def _refresh_stale_activities(
    *,
    client: StravaClient,
    storage: GitHubStorage,
    result: SyncResult,
    skip_ids: set[int],
) -> None:
    """Re-fetch description, location, laps, polyline, and photos for any
    already-stored Strava activities that are missing those fields.

    Conservative: skips activities with any sign of already-fetched detail
    (non-empty summary or non-empty laps). Activities that legitimately have
    nothing to add (e.g. a treadmill run with no description and no laps in
    Strava) get one detail call but no commit, because we compare before
    rewriting.

    ``skip_ids`` short-circuits activities that were already detail-fetched
    earlier in this sync (the import path). Returns early on rate-limit so
    the user gets a clear "try again later" message instead of partial,
    silently-failed refreshes that look like missing data.
    """
    for path in storage.list_activities():
        try:
            loaded = storage.load_activity(path)
        except Exception:
            continue
        if loaded is None:
            continue
        activity, body = loaded
        if not _is_stale(activity):
            continue
        if activity.metrics is None or not activity.metrics.strava_id:
            continue
        strava_id = activity.metrics.strava_id
        if strava_id in skip_ids:
            continue
        try:
            detail = client.activity_detail(strava_id)
            if not detail:
                continue
            photo_urls: list[str] = list(activity.metrics.photo_urls)
            if detail.get("total_photo_count", 0) and not photo_urls:
                photo_urls = client.activity_photos(strava_id)
            # Strava's detail response is a superset of summary so we can use
            # it as both. If the dict happens to lack the date field (older
            # API, partial test stub), fall back to the stored date so we
            # don't blow up on parsing.
            if not detail.get("start_date_local") and not detail.get("start_date"):
                detail = {
                    **detail,
                    "start_date_local": activity.activity_date.isoformat()
                    + "T00:00:00Z",
                }
            if not detail.get("id"):
                detail = {**detail, "id": strava_id}
            refreshed = _activity_from_summary(detail, photo_urls, detail)

            # Enhance with LLM parsing if a description is present
            desc = (detail.get("description") or "").strip()
            if desc:
                refreshed = _enhance_with_llm(refreshed, desc)

            # Preserve user-edited fields. Title / rpe / intensity / notes
            # could all have been touched via the reviser agent.
            refreshed.title = activity.title
            refreshed.rpe = activity.rpe
            refreshed.intensity = activity.intensity or refreshed.intensity
            refreshed.created_at = activity.created_at
            if activity.notes and not refreshed.notes:
                refreshed.notes = activity.notes

            # Skip the commit when Strava genuinely has no new info — e.g. an
            # untitled treadmill run with no description and no laps.
            before = activity.model_dump(mode="json", exclude={"updated_at"})
            after = refreshed.model_dump(mode="json", exclude={"updated_at"})
            if before == after:
                continue

            storage.update_activity(path, refreshed, body)
            result.refreshed.append(path)
        except StravaRateLimitError as exc:
            result.rate_limited = True
            result.errors.append(str(exc))
            return
        except Exception as exc:
            result.errors.append(f"Refresh {strava_id}: {exc}")


def sync_recent(
    *,
    client: StravaClient,
    storage: GitHubStorage,
    since: Optional[date] = None,
    body_template: str = "Synced from Strava.",
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
) -> SyncResult:
    """Import recent Strava activities into the data repo and refresh stale ones.

    The fetch window always extends ``lookback_days`` back from today, so
    re-clicking Sync after a code update will pick up activities that pre-date
    the previous run. Dedup keeps re-syncs fast — only the list pagination
    cost (≈1 call per 50 activities) is paid; existing IDs short-circuit
    before any detail / photo calls.

    Activities already stored under the pre-laps schema (no description,
    location, or laps) get auto-refreshed in place using a single detail call
    per activity. User-edited fields (title, RPE, intensity, notes) are
    preserved.

    Args:
        client: Authenticated Strava client.
        storage: Destination GitHub storage.
        since: Override the "fetch from" date. Defaults to ``lookback_days``
            ago so the full history is always considered.
        body_template: Markdown body to use for newly imported activities.
        lookback_days: How far back to look on every sync. Defaults to 10
            years.

    Returns:
        A :class:`SyncResult` listing newly imported, in-place-refreshed,
        and per-activity errors.
    """
    result = SyncResult()

    if since is None:
        since = date.today() - timedelta(days=lookback_days)

    try:
        summaries = client.recent_activities(since=since)
    except StravaError as exc:
        result.errors.append(f"Strava fetch failed: {exc}")
        return result

    existing = _existing_strava_ids(storage)
    just_imported: set[int] = set()

    for summary in summaries:
        strava_id = summary.get("id")
        if not strava_id:
            continue
        if strava_id in existing:
            result.skipped_existing += 1
            continue

        try:
            photo_urls: list[str] = []
            if summary.get("total_photo_count", 0):
                photo_urls = client.activity_photos(strava_id)
            # Detail call gives us the description + laps (absent from the
            # list endpoint). Empty dict on failure → we just lose those fields.
            detail = client.activity_detail(strava_id)
            activity = _activity_from_summary(summary, photo_urls, detail or None)

            # Enhance with LLM parsing if a description is present
            desc = (detail.get("description") or "").strip() if detail else ""
            if desc:
                activity = _enhance_with_llm(activity, desc)

            path = storage.save_activity(activity, body=body_template)
        except StravaRateLimitError as exc:
            # Stop importing immediately — continuing would either keep
            # hitting 429s or quietly store activities with missing detail
            # (the exact bug we're trying to prevent).
            result.rate_limited = True
            result.errors.append(str(exc))
            return result
        except Exception as exc:
            result.errors.append(f"Activity {strava_id}: {exc}")
            continue

        result.imported.append(path)
        existing.add(strava_id)
        just_imported.add(strava_id)

    # Backfill description / location / laps on activities that were stored
    # before those fields were captured. Just-imported IDs are skipped — we
    # already pulled their detail above.
    _refresh_stale_activities(
        client=client,
        storage=storage,
        result=result,
        skip_ids=just_imported,
    )

    return result
