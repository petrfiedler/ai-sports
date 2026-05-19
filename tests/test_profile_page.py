"""Smoke tests for the Profile page using ``AppTest`` with stubbed services."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from src.config import get_settings
from src.models.schemas import ProfileSchema, SportType


PROFILE_PAGE = "src/ui/pages/4_Profile.py"
PASSWORD = "letmein"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_DATA_REPO", "test/test-repo")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    get_settings.cache_clear()


class FakeStorage:
    """In-memory stand-in used by the profile page."""

    def __init__(self) -> None:
        self.profile: ProfileSchema | None = None
        self.saved: list[ProfileSchema] = []

    def load_profile(self) -> ProfileSchema | None:
        return self.profile

    def save_profile(self, profile: ProfileSchema) -> None:
        self.profile = profile
        self.saved.append(profile)


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def patch_services(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> FakeStorage:
    monkeypatch.setattr("src.ui.services.get_storage", lambda: fake_storage)
    monkeypatch.setattr("src.ui.services.load_profile", lambda: fake_storage.profile)
    monkeypatch.setattr("src.ui.services.clear_profile_cache", lambda: None)
    return fake_storage


def _authenticate(at: AppTest) -> AppTest:
    at.text_input[0].set_value(PASSWORD).run()
    return at


def test_empty_profile_renders_form(patch_services: FakeStorage) -> None:
    at = AppTest.from_file(PROFILE_PAGE).run()
    _authenticate(at)
    assert not at.exception
    assert any("No profile yet" in str(i.value) for i in at.info)
    # Form fields: name input + 3 text areas (goals, constraints, narrative).
    assert any("Name" in (ti.label or "") for ti in at.text_input)


def test_existing_profile_prefills_fields(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    fake_storage.profile = ProfileSchema(
        name="Petr",
        goals=["Half marathon under 2h"],
        preferred_sports=[SportType.RUNNING],
        weekly_target_hours=6.0,
        constraints=["No gym Tuesdays"],
        narrative="Recreational athlete.",
    )
    at = AppTest.from_file(PROFILE_PAGE).run()
    _authenticate(at)
    assert not at.exception
    name_input = next((ti for ti in at.text_input if "Name" in (ti.label or "")), None)
    assert name_input is not None
    assert name_input.value == "Petr"


def test_submit_saves_profile(
    patch_services: FakeStorage, fake_storage: FakeStorage
) -> None:
    at = AppTest.from_file(PROFILE_PAGE).run()
    _authenticate(at)
    name_input = next(ti for ti in at.text_input if "Name" in (ti.label or ""))
    name_input.set_value("Petr").run()
    goals_input = next(ta for ta in at.text_area if "Goals" in (ta.label or ""))
    goals_input.set_value("Half marathon under 2h\nBoulder V6").run()
    save_btn = next(b for b in at.button if b.label == "Save profile")
    save_btn.click().run()
    assert not at.exception
    assert len(fake_storage.saved) == 1
    saved = fake_storage.saved[0]
    assert saved.name == "Petr"
    assert saved.goals == ["Half marathon under 2h", "Boulder V6"]
