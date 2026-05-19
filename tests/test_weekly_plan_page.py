"""Smoke tests for the Weekly Plan page using ``AppTest`` with stubbed services."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from src.agents.planner_agent import PlanResult
from src.config import get_settings
from src.models.schemas import (
    Intensity,
    PlanSchema,
    PlannedActivity,
    ProfileSchema,
    SportType,
)


PLAN_PAGE = "src/ui/pages/3_Weekly_Plan.py"
PASSWORD = "letmein"
NEXT_MONDAY = date(2026, 5, 18)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_DATA_REPO", "test/test-repo")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()


class FakeStorage:
    """In-memory stand-in for ``GitHubStorage`` used by the plan page."""

    def __init__(self) -> None:
        self.plan: tuple[PlanSchema, str] | None = None
        self.profile: ProfileSchema | None = None
        self.saved_plans: list[tuple[PlanSchema, str]] = []

    def load_current_plan(self) -> tuple[PlanSchema, str] | None:
        return self.plan

    def save_plan(self, plan: PlanSchema, body: str = "") -> str:
        self.plan = (plan, body)
        self.saved_plans.append((plan, body))
        return f"plans/{plan.week_start.isoformat()}-plan.md"

    def load_profile(self) -> ProfileSchema | None:
        return self.profile


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def patch_services(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> FakeStorage:
    monkeypatch.setattr("src.ui.services.get_storage", lambda: fake_storage)
    monkeypatch.setattr(
        "src.ui.services.load_current_plan", lambda: fake_storage.load_current_plan()
    )
    monkeypatch.setattr("src.ui.services.load_profile", lambda: fake_storage.profile)
    monkeypatch.setattr(
        "src.ui.services.load_recent_activities_for_planning", lambda days=14: []
    )
    monkeypatch.setattr("src.ui.services.clear_plan_cache", lambda: None)
    monkeypatch.setattr("src.ui.services.next_monday", lambda today=None: NEXT_MONDAY)
    return fake_storage


def _existing_plan() -> PlanSchema:
    return PlanSchema(
        week_start=NEXT_MONDAY,
        activities=[
            PlannedActivity(
                day=NEXT_MONDAY,
                sport=SportType.RUNNING,
                title="Easy run",
                description="Z2 35 min",
                duration_minutes=35,
                intensity=Intensity.LOW,
            ),
            PlannedActivity(
                day=NEXT_MONDAY + timedelta(days=1),
                sport=SportType.STRENGTH,
                title="Lower body",
                description="Squats, RDLs",
                duration_minutes=60,
                intensity=Intensity.HIGH,
            ),
        ],
        rationale="Hard / easy alternation.",
    )


def _authenticate(at: AppTest) -> AppTest:
    at.text_input[0].set_value(PASSWORD).run()
    return at


def test_empty_state_offers_generate_button(patch_services: FakeStorage) -> None:
    at = AppTest.from_file(PLAN_PAGE).run()
    _authenticate(at)
    assert not at.exception
    assert any("No plan yet" in str(i.value) for i in at.info)
    assert any(b.label == "Generate plan" for b in at.button)


def test_existing_plan_renders_day_cards(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    fake_storage.plan = (_existing_plan(), "Hard / easy alternation.")
    at = AppTest.from_file(PLAN_PAGE).run()
    _authenticate(at)
    assert not at.exception
    assert any("Easy run" in (m.value or "") for m in at.markdown)
    assert any("Lower body" in (m.value or "") for m in at.markdown)


def test_generate_button_calls_planner_and_saves_plan(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    generated = _existing_plan()
    monkeypatch.setattr(
        "src.agents.planner_agent.generate_plan",
        lambda profile, recent, week_start, **_kw: PlanResult(plan=generated),
    )
    at = AppTest.from_file(PLAN_PAGE).run()
    _authenticate(at)
    gen_btn = next((b for b in at.button if b.label == "Generate plan"), None)
    assert gen_btn is not None
    gen_btn.click().run()
    assert not at.exception
    assert len(fake_storage.saved_plans) == 1
    saved, _body = fake_storage.saved_plans[0]
    assert saved.week_start == NEXT_MONDAY


def test_generate_fallback_shows_warning(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    monkeypatch.setattr(
        "src.agents.planner_agent.generate_plan",
        lambda profile, recent, week_start, **_kw: PlanResult(
            fallback_message="Could not build a plan."
        ),
    )
    at = AppTest.from_file(PLAN_PAGE).run()
    _authenticate(at)
    gen_btn = next((b for b in at.button if b.label == "Generate plan"), None)
    assert gen_btn is not None
    gen_btn.click().run()
    assert not at.exception
    assert any("Could not build" in str(w.value) for w in at.warning)
    assert fake_storage.saved_plans == []


def test_revise_applies_edit_and_saves(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    current = _existing_plan()
    fake_storage.plan = (current, current.rationale or "")

    revised_activities = [
        a.model_copy(update={"day": a.day + timedelta(days=1)})
        if a.sport == SportType.STRENGTH.value
        else a
        for a in current.activities
    ]
    revised = current.model_copy(update={"activities": revised_activities})
    monkeypatch.setattr(
        "src.agents.planner_agent.revise_plan",
        lambda c, instruction, **_kw: PlanResult(plan=revised),
    )

    at = AppTest.from_file(PLAN_PAGE).run()
    _authenticate(at)
    at.text_input[0].set_value("move Tuesday's strength to Wednesday").run()
    apply_btn = next((b for b in at.button if b.label == "Apply"), None)
    assert apply_btn is not None
    apply_btn.click().run()
    assert not at.exception
    assert len(fake_storage.saved_plans) == 1
    saved, _body = fake_storage.saved_plans[0]
    strength = next(a for a in saved.activities if a.sport == SportType.STRENGTH.value)
    assert strength.day == NEXT_MONDAY + timedelta(days=2)


def test_revise_fallback_keeps_existing_plan(
    monkeypatch: pytest.MonkeyPatch,
    patch_services: FakeStorage,
    fake_storage: FakeStorage,
) -> None:
    current = _existing_plan()
    fake_storage.plan = (current, current.rationale or "")
    monkeypatch.setattr(
        "src.agents.planner_agent.revise_plan",
        lambda c, instruction, **_kw: PlanResult(
            plan=c, fallback_message="Couldn't apply edit."
        ),
    )
    at = AppTest.from_file(PLAN_PAGE).run()
    _authenticate(at)
    at.text_input[0].set_value("nonsense").run()
    apply_btn = next((b for b in at.button if b.label == "Apply"), None)
    assert apply_btn is not None
    apply_btn.click().run()
    assert not at.exception
    assert fake_storage.saved_plans == []
    assert any("Couldn't apply" in str(w.value) for w in at.warning)


def test_completion_toggle_writes_back(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    current = _existing_plan()
    fake_storage.plan = (current, current.rationale or "")
    at = AppTest.from_file(PLAN_PAGE).run()
    _authenticate(at)
    assert at.checkbox, "expected per-day completion checkboxes"
    at.checkbox[0].check().run()
    assert not at.exception
    assert len(fake_storage.saved_plans) == 1
    saved, _body = fake_storage.saved_plans[0]
    assert any(a.completed for a in saved.activities)
