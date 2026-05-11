"""Smoke tests for the Activity Detail page via ``AppTest``.

Uses an in-memory ``FakeStorage`` and stubbed revise/parse functions so the
tests never touch GitHub or Anthropic.
"""

from __future__ import annotations

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from src.config import get_settings
from src.models.schemas import (
    ActivitySchema,
    EnduranceMetrics,
    Exercise,
    ExerciseSet,
    FollowUpQuestion,
    ParseResult,
    SportType,
)


DETAIL_PAGE = "src/ui/pages/2_Activity_Detail.py"
PASSWORD = "letmein"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_DATA_REPO", "test/test-repo")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()


class FakeStorage:
    """In-memory stand-in for ``GitHubStorage`` used by the detail page."""

    def __init__(self) -> None:
        self.activities: dict[str, tuple[ActivitySchema, str]] = {}
        self.updates: list[tuple[str, ActivitySchema, str]] = []
        self.deleted: list[str] = []

    def load_activity(self, path: str) -> tuple[ActivitySchema, str] | None:
        return self.activities.get(path)

    def update_activity(self, path: str, activity: ActivitySchema, body: str) -> None:
        self.updates.append((path, activity, body))
        self.activities[path] = (activity, body)

    def delete_activity(self, path: str) -> None:
        self.deleted.append(path)
        self.activities.pop(path, None)


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def patch_services(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> FakeStorage:
    monkeypatch.setattr("src.ui.services.get_storage", lambda: fake_storage)

    def _list(*_args: object, **_kwargs: object) -> list[tuple[str, ActivitySchema]]:
        return [(p, a) for p, (a, _b) in fake_storage.activities.items()]

    _list.clear = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr("src.ui.services.list_recent_activities", _list)
    return fake_storage


def _running_activity() -> ActivitySchema:
    return ActivitySchema(
        title="Morning run",
        sport=SportType.RUNNING,
        activity_date=date(2026, 5, 10),
        duration_minutes=30,
        rpe=4,
        metrics=EnduranceMetrics(distance_km=5.0, avg_heart_rate=148),
        notes="Felt good.",
    )


def _strength_activity() -> ActivitySchema:
    return ActivitySchema(
        title="Push day",
        sport=SportType.STRENGTH,
        activity_date=date(2026, 5, 11),
        duration_minutes=60,
        exercises=[
            Exercise(
                name="Bench press",
                sets=[
                    ExerciseSet(reps=8, weight_kg=80, rest_seconds=120),
                    ExerciseSet(reps=6, weight_kg=85),
                ],
            )
        ],
    )


def _authenticate(at: AppTest) -> AppTest:
    at.text_input[0].set_value(PASSWORD).run()
    return at


def _seed(fake_storage: FakeStorage, path: str, activity: ActivitySchema, body: str = "") -> None:
    fake_storage.activities[path] = (activity, body)


def test_no_path_shows_empty_state(patch_services: FakeStorage) -> None:
    at = AppTest.from_file(DETAIL_PAGE).run()
    _authenticate(at)
    assert not at.exception
    assert any("No activity selected" in str(i.value) for i in at.info)


def test_running_activity_renders_header_and_metrics(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    path = "activities/2026-05-10-morning-run.md"
    _seed(fake_storage, path, _running_activity(), body="ran 5k easy")
    at = AppTest.from_file(DETAIL_PAGE)
    at.query_params["path"] = path
    at.run()
    _authenticate(at)
    assert not at.exception
    assert any("Morning run" in (h.value or "") for h in at.header)
    assert any("Distance" == m.label for m in at.metric)
    assert any("Avg HR" == m.label for m in at.metric)


def test_strength_activity_renders_exercise_table(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    path = "activities/2026-05-11-push-day.md"
    _seed(fake_storage, path, _strength_activity())
    at = AppTest.from_file(DETAIL_PAGE)
    at.query_params["path"] = path
    at.run()
    _authenticate(at)
    assert not at.exception
    assert any("Bench press" in (m.value or "") for m in at.markdown)


def test_missing_activity_warns(patch_services: FakeStorage) -> None:
    at = AppTest.from_file(DETAIL_PAGE)
    at.query_params["path"] = "activities/does-not-exist.md"
    at.run()
    _authenticate(at)
    assert not at.exception
    assert any("no longer exists" in str(w.value) for w in at.warning)


def test_master_edit_applies_revision(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    path = "activities/2026-05-10-morning-run.md"
    original = _running_activity()
    _seed(fake_storage, path, original, body="ran 5k easy")

    revised = original.model_copy(update={"duration_minutes": 45})
    monkeypatch.setattr(
        "src.agents.parser_agent.revise_activity",
        lambda current, instruction, **_kw: ParseResult(activity=revised),
    )

    at = AppTest.from_file(DETAIL_PAGE)
    at.query_params["path"] = path
    at.run()
    _authenticate(at)
    # First text_input is the master-edit field (no follow-ups pending).
    at.text_input[0].set_value("actually 45 minutes").run()
    at.button[0].click().run()
    assert not at.exception
    assert len(fake_storage.updates) == 1
    saved_path, saved_activity, _body = fake_storage.updates[0]
    assert saved_path == path
    assert saved_activity.duration_minutes == 45


def test_master_edit_fallback_keeps_state(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    path = "activities/2026-05-10-morning-run.md"
    current = _running_activity()
    _seed(fake_storage, path, current)
    monkeypatch.setattr(
        "src.agents.parser_agent.revise_activity",
        lambda current, instruction, **_kw: ParseResult(
            activity=current, fallback_message="Couldn't apply that edit."
        ),
    )

    at = AppTest.from_file(DETAIL_PAGE)
    at.query_params["path"] = path
    at.run()
    _authenticate(at)
    at.text_input[0].set_value("nonsense").run()
    at.button[0].click().run()
    assert not at.exception
    assert fake_storage.updates == []
    assert any("Couldn't apply" in str(w.value) for w in at.warning)


def test_followup_questions_apply_and_clear(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    path = "activities/2026-05-10-morning-run.md"
    original = _running_activity()
    _seed(fake_storage, path, original)

    revised = original.model_copy(update={"rpe": 7})
    monkeypatch.setattr(
        "src.agents.parser_agent.revise_activity",
        lambda current, instruction, **_kw: ParseResult(activity=revised),
    )

    at = AppTest.from_file(DETAIL_PAGE)
    at.query_params["path"] = path
    at.session_state["follow_ups"] = {
        path: [FollowUpQuestion(field="rpe", question="How hard was it?").model_dump()]
    }
    at.run()
    _authenticate(at)
    # First text_input is the follow-up answer; second is the master edit field.
    at.text_input[0].set_value("7/10").run()
    # First form submit button is the follow-ups form.
    at.button[0].click().run()
    assert not at.exception
    assert len(fake_storage.updates) >= 1
    # Follow-ups for this path should be cleared.
    assert path not in at.session_state["follow_ups"]


def test_delete_removes_activity(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    path = "activities/2026-05-10-morning-run.md"
    _seed(fake_storage, path, _running_activity())
    at = AppTest.from_file(DETAIL_PAGE)
    at.query_params["path"] = path
    at.run()
    _authenticate(at)
    # The popover trigger is a button labelled 'Delete activity'; clicking
    # it does not itself delete — the inner 'Confirm delete' button does.
    confirm = next((b for b in at.button if b.label == "Confirm delete"), None)
    assert confirm is not None
    confirm.click().run()
    assert path in fake_storage.deleted
