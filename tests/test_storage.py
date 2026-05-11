"""Tests for src.services.storage using an in-memory fake Repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from github import GithubException

from src.models.schemas import (
    ActivitySchema,
    Exercise,
    ExerciseSet,
    PlanSchema,
    PlannedActivity,
    ProfileSchema,
    SportType,
)
from src.services.storage import (
    GitHubStorage,
    _activity_path,
    _plan_path,
    _slugify,
)


@dataclass
class FakeContentFile:
    path: str
    decoded_content: bytes
    sha: str = "deadbeef"


class FakeRepo:
    """Minimal in-memory stand-in for github.Repository.Repository."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.commits: list[tuple[str, str]] = []

    def _not_found(self, path: str) -> GithubException:
        return GithubException(404, {"message": f"Not Found: {path}"}, None)

    def get_contents(self, path: str, ref: str = "main"):
        if path in self.files:
            return FakeContentFile(path=path, decoded_content=self.files[path])
        prefix = path.rstrip("/") + "/"
        children = [
            FakeContentFile(path=p, decoded_content=v)
            for p, v in self.files.items()
            if p.startswith(prefix)
        ]
        if children:
            return children
        raise self._not_found(path)

    def create_file(
        self, path: str, message: str, content: str, branch: str = "main"
    ) -> None:
        if path in self.files:
            raise GithubException(422, {"message": "Already exists"}, None)
        self.files[path] = content.encode("utf-8")
        self.commits.append((path, message))

    def update_file(
        self,
        path: str,
        message: str,
        content: str,
        sha: str,
        branch: str = "main",
    ) -> None:
        self.files[path] = content.encode("utf-8")
        self.commits.append((path, message))

    def delete_file(
        self, path: str, message: str, sha: str, branch: str = "main"
    ) -> None:
        del self.files[path]
        self.commits.append((path, f"DELETE {message}"))


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def storage(repo: FakeRepo) -> GitHubStorage:
    return GitHubStorage(repo=repo)  # type: ignore[arg-type]


# --- helpers ---------------------------------------------------------------


def test_slugify_handles_czech_diacritics() -> None:
    assert _slugify("Příjemný běh v lese") == "prijemny-beh-v-lese"


def test_slugify_collapses_punctuation_and_whitespace() -> None:
    assert _slugify("Bouldering -- V4/V5 overhangs!") == "bouldering-v4-v5-overhangs"


def test_slugify_falls_back_when_empty() -> None:
    assert _slugify("   ") == "untitled"
    assert _slugify("???") == "untitled"


def test_activity_path_format() -> None:
    assert (
        _activity_path(date(2026, 5, 11), "Easy run")
        == "activities/2026-05-11-easy-run.md"
    )


def test_plan_path_uses_iso_week() -> None:
    # 2026-05-11 is a Monday in ISO week 20.
    assert _plan_path(date(2026, 5, 11)) == "plans/2026-W20-plan.md"


# --- low-level file ops ----------------------------------------------------


def test_read_file_returns_none_when_missing(storage: GitHubStorage) -> None:
    assert storage.read_file("nonexistent.md") is None


def test_write_file_creates_then_updates(
    storage: GitHubStorage, repo: FakeRepo
) -> None:
    storage.write_file("hello.md", "v1", "first")
    assert repo.files["hello.md"] == b"v1"
    storage.write_file("hello.md", "v2", "second")
    assert repo.files["hello.md"] == b"v2"
    assert [m for _, m in repo.commits] == ["first", "second"]


def test_list_dir_empty_for_missing_directory(storage: GitHubStorage) -> None:
    assert storage.list_dir("missing/") == []


# --- activity round-trip ---------------------------------------------------


def test_save_then_load_activity_round_trip(storage: GitHubStorage) -> None:
    activity = ActivitySchema(
        title="Easy run",
        sport=SportType.RUNNING,
        activity_date=date(2026, 5, 11),
        duration_minutes=30,
        rpe=4,
    )
    path = storage.save_activity(activity, "Felt great today.")
    assert path == "activities/2026-05-11-easy-run.md"

    loaded = storage.load_activity(path)
    assert loaded is not None
    loaded_activity, body = loaded
    assert loaded_activity.title == "Easy run"
    # ActivitySchema uses use_enum_values=True, so sport is a plain string.
    assert loaded_activity.sport == "running"
    assert loaded_activity.activity_date == date(2026, 5, 11)
    assert loaded_activity.duration_minutes == 30
    assert loaded_activity.rpe == 4
    assert body.strip() == "Felt great today."


def test_save_activity_writes_yaml_frontmatter(
    storage: GitHubStorage, repo: FakeRepo
) -> None:
    activity = ActivitySchema(
        title="Strength",
        sport=SportType.STRENGTH,
        activity_date=date(2026, 5, 11),
        duration_minutes=45,
        exercises=[Exercise(name="Squat", sets=[ExerciseSet(reps=5, weight_kg=80.0)])],
    )
    path = storage.save_activity(activity, "")
    raw = repo.files[path].decode("utf-8")
    assert raw.startswith("---\n")
    assert "sport: strength" in raw
    assert "Squat" in raw


def test_load_activity_returns_none_when_missing(storage: GitHubStorage) -> None:
    assert storage.load_activity("activities/2026-01-01-nope.md") is None


def test_list_activities_newest_first(storage: GitHubStorage) -> None:
    for d in (date(2026, 5, 1), date(2026, 5, 10), date(2026, 4, 20)):
        storage.save_activity(
            ActivitySchema(
                title=f"Run {d.isoformat()}",
                sport=SportType.RUNNING,
                activity_date=d,
                duration_minutes=30,
            ),
            "",
        )
    paths = storage.list_activities()
    assert paths[0].startswith("activities/2026-05-10")
    assert paths[-1].startswith("activities/2026-04-20")


def test_list_activities_filters_by_year(storage: GitHubStorage) -> None:
    storage.save_activity(
        ActivitySchema(
            title="Old",
            sport=SportType.RUNNING,
            activity_date=date(2025, 12, 30),
            duration_minutes=30,
        ),
        "",
    )
    storage.save_activity(
        ActivitySchema(
            title="New",
            sport=SportType.RUNNING,
            activity_date=date(2026, 1, 5),
            duration_minutes=30,
        ),
        "",
    )
    assert all(p.startswith("activities/2026-") for p in storage.list_activities(year=2026))
    assert all(p.startswith("activities/2025-") for p in storage.list_activities(year=2025))


def test_delete_activity(storage: GitHubStorage) -> None:
    path = storage.save_activity(
        ActivitySchema(
            title="X",
            sport=SportType.RUNNING,
            activity_date=date(2026, 5, 11),
            duration_minutes=10,
        ),
        "",
    )
    storage.delete_activity(path)
    assert storage.load_activity(path) is None


# --- profile ---------------------------------------------------------------


def test_load_profile_returns_none_when_missing(storage: GitHubStorage) -> None:
    assert storage.load_profile() is None


def test_save_then_load_profile(storage: GitHubStorage) -> None:
    profile = ProfileSchema(
        name="Petr",
        goals=["Half marathon under 2h"],
        preferred_sports=[SportType.RUNNING, SportType.BOULDERING],
        weekly_target_hours=6.5,
        constraints=["No gym on Tuesdays"],
        narrative="Balance climbing with running.",
    )
    storage.save_profile(profile)
    loaded = storage.load_profile()
    assert loaded is not None
    assert loaded.name == "Petr"
    assert loaded.goals == ["Half marathon under 2h"]
    assert loaded.preferred_sports == ["running", "bouldering"]
    assert loaded.weekly_target_hours == 6.5
    assert loaded.narrative == "Balance climbing with running."


# --- plans -----------------------------------------------------------------


def test_save_and_load_current_plan(storage: GitHubStorage) -> None:
    plan = PlanSchema(
        week_start=date(2026, 5, 11),
        activities=[
            PlannedActivity(
                day=date(2026, 5, 12),
                sport=SportType.RUNNING,
                title="Easy 5k",
                description="Zone 2.",
                duration_minutes=30,
            )
        ],
        rationale="Build aerobic base.",
    )
    path = storage.save_plan(plan)
    assert path == "plans/2026-W20-plan.md"

    loaded = storage.load_current_plan()
    assert loaded is not None
    loaded_plan, _ = loaded
    assert loaded_plan.week_start == date(2026, 5, 11)
    assert len(loaded_plan.activities) == 1
    assert loaded_plan.activities[0].title == "Easy 5k"


def test_load_current_plan_picks_latest_iso_week(storage: GitHubStorage) -> None:
    older = PlanSchema(week_start=date(2026, 5, 4))   # ISO week 19
    newer = PlanSchema(week_start=date(2026, 5, 11))  # ISO week 20
    storage.save_plan(older)
    storage.save_plan(newer)
    loaded = storage.load_current_plan()
    assert loaded is not None
    plan, _ = loaded
    assert plan.week_start == date(2026, 5, 11)


def test_load_current_plan_returns_none_when_empty(storage: GitHubStorage) -> None:
    assert storage.load_current_plan() is None
