"""Smoke tests for the Dashboard page using ``AppTest`` with stubbed services."""

from __future__ import annotations

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from src.config import get_settings
from src.models.schemas import ActivitySchema, FollowUpQuestion, ParseResult, SportType


DASHBOARD_PAGE = "src/ui/pages/1_Dashboard.py"
PASSWORD = "letmein"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_DATA_REPO", "test/test-repo")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()


class FakeStorage:
    """In-memory stand-in for :class:`GitHubStorage` used by the dashboard."""

    def __init__(self) -> None:
        self.activities: list[tuple[str, ActivitySchema]] = []
        self.saved: list[tuple[ActivitySchema, str]] = []

    def save_activity(self, activity: ActivitySchema, body: str) -> str:
        path = f"activities/{activity.activity_date.isoformat()}-test.md"
        self.saved.append((activity, body))
        self.activities.insert(0, (path, activity))
        return path


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def patch_services(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> FakeStorage:
    monkeypatch.setattr("src.ui.services.get_storage", lambda: fake_storage)
    # Strava is optional and stubbed off; Sync button stays disabled.
    monkeypatch.setattr("src.ui.services.get_strava_client", lambda: None)

    def _list(
        limit: int = 10, offset: int = 0, **_kwargs: object
    ) -> tuple[list[tuple[str, ActivitySchema]], int]:
        window = fake_storage.activities[offset : offset + limit]
        return window, len(fake_storage.activities)

    monkeypatch.setattr("src.ui.services.list_recent_activities", _list)
    monkeypatch.setattr("src.ui.services.clear_activity_caches", lambda: None)
    return fake_storage


def _authenticate(at: AppTest) -> AppTest:
    at.text_input[0].set_value(PASSWORD).run()
    return at


def test_password_gate_blocks_until_correct(patch_services: FakeStorage) -> None:
    at = AppTest.from_file(DASHBOARD_PAGE).run()
    assert not at.exception
    assert any("Password" in (i.label or "") for i in at.text_input)
    assert not any(h.value == "Dashboard" for h in at.header)


def test_empty_state_renders_for_authenticated_user(patch_services: FakeStorage) -> None:
    at = AppTest.from_file(DASHBOARD_PAGE).run()
    _authenticate(at)
    assert not at.exception
    assert any(h.value == "Dashboard" for h in at.header)
    assert any("No activities yet" in str(i.value) for i in at.info)


def test_recent_activities_render_with_weekly_metric(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    today = date.today()
    fake_storage.activities = [
        (
            "activities/2026-05-10-easy-run.md",
            ActivitySchema(
                title="Easy run",
                sport=SportType.RUNNING,
                activity_date=today,
                duration_minutes=30,
                rpe=4,
            ),
        ),
    ]
    at = AppTest.from_file(DASHBOARD_PAGE).run()
    _authenticate(at)
    assert not at.exception
    assert any("Easy run" in m.value for m in at.markdown)
    # Weekly metric is rendered when there is at least one activity this week.
    assert any("30 min" in str(getattr(m, "value", "")) for m in at.metric)


def test_quick_add_saves_parsed_activity(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    parsed = ActivitySchema(
        title="Lunch run",
        sport=SportType.RUNNING,
        activity_date=date.today(),
        duration_minutes=25,
    )
    monkeypatch.setattr(
        "src.agents.parser_agent.parse_activity",
        lambda text, **_kw: ParseResult(activity=parsed),
    )
    at = AppTest.from_file(DASHBOARD_PAGE).run()
    _authenticate(at)
    at.text_area[0].set_value("25 min lunch run").run()
    # button[0] is the Sync Strava button (disabled in tests); the Quick Add
    # submit is the second button.
    at.button[1].click().run()
    assert not at.exception
    assert len(fake_storage.saved) == 1
    saved_activity, saved_body = fake_storage.saved[0]
    assert saved_activity.title == "Lunch run"
    assert saved_body == "25 min lunch run"


def test_quick_add_renders_fallback_when_parser_fails(
    monkeypatch: pytest.MonkeyPatch, patch_services: FakeStorage
) -> None:
    monkeypatch.setattr(
        "src.agents.parser_agent.parse_activity",
        lambda text, **_kw: ParseResult(fallback_message="Couldn't parse that."),
    )
    at = AppTest.from_file(DASHBOARD_PAGE).run()
    _authenticate(at)
    at.text_area[0].set_value("asdf").run()
    # button[0] is the Sync Strava button (disabled in tests); the Quick Add
    # submit is the second button.
    at.button[1].click().run()
    assert not at.exception
    assert any("Couldn't parse" in str(w.value) for w in at.warning)


def test_load_more_increases_displayed_count(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    """With more than one page of activities, a Load more button appears."""
    today = date.today()
    fake_storage.activities = [
        (
            f"activities/2026-{(i % 12) + 1:02d}-01-x.md",
            ActivitySchema(
                title=f"Run {i}",
                sport=SportType.RUNNING,
                activity_date=today,
                duration_minutes=20,
            ),
        )
        for i in range(15)
    ]
    at = AppTest.from_file(DASHBOARD_PAGE).run()
    _authenticate(at)
    # Default page size is 10 → 5 activities should remain behind a Load more.
    assert any("Load 5 more" in (b.label or "") for b in at.button)


def test_quick_add_stashes_follow_up_questions(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
) -> None:
    parsed = ActivitySchema(
        title="Run",
        sport=SportType.RUNNING,
        activity_date=date.today(),
        duration_minutes=20,
    )
    monkeypatch.setattr(
        "src.agents.parser_agent.parse_activity",
        lambda text, **_kw: ParseResult(
            activity=parsed,
            questions=[FollowUpQuestion(field="rpe", question="How hard was it?")],
        ),
    )
    at = AppTest.from_file(DASHBOARD_PAGE).run()
    _authenticate(at)
    at.text_area[0].set_value("a quick run").run()
    # button[0] is the Sync Strava button (disabled in tests); the Quick Add
    # submit is the second button.
    at.button[1].click().run()
    assert not at.exception
    assert "follow_ups" in at.session_state
    follow_ups = at.session_state["follow_ups"]
    assert any(
        any(q["field"] == "rpe" for q in qs) for qs in follow_ups.values()
    )
