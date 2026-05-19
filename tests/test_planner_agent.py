"""Tests for the Planner Agent.

The tests inject a stubbed smolagents ``Model`` that replays canned
``submit_plan`` calls, so nothing here touches the real Anthropic API.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from smolagents import Model
from smolagents.models import (
    ChatMessage,
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    MessageRole,
)

from src.agents.planner_agent import generate_plan, revise_plan
from src.models.schemas import (
    ActivitySchema,
    Intensity,
    PlanSchema,
    PlannedActivity,
    ProfileSchema,
    SportType,
)


TODAY = date(2026, 5, 13)  # Wednesday
NEXT_MONDAY = date(2026, 5, 18)


class ScriptedModel(Model):
    """Replays a fixed sequence of tool calls back to the agent."""

    def __init__(self, script: list[tuple[str, dict[str, Any]]]) -> None:
        super().__init__()
        self._script = list(script)
        self.call_count = 0

    def generate(  # type: ignore[override]
        self,
        messages: Any,
        stop_sequences: Optional[list[str]] = None,
        response_format: Optional[dict[str, str]] = None,
        tools_to_call_from: Optional[list[Any]] = None,
        **kwargs: Any,
    ) -> ChatMessage:
        self.call_count += 1
        if not self._script:
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=[
                    ChatMessageToolCall(
                        id=f"call_{self.call_count}",
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name="final_answer", arguments={"answer": "done"}
                        ),
                    )
                ],
            )
        name, arguments = self._script.pop(0)
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=[
                ChatMessageToolCall(
                    id=f"call_{self.call_count}",
                    type="function",
                    function=ChatMessageToolCallFunction(
                        name=name, arguments=arguments
                    ),
                )
            ],
        )


def _submit_plan_then_finish(plan: Optional[dict[str, Any]]) -> ScriptedModel:
    return ScriptedModel(
        [
            ("submit_plan", {"plan": plan}),
            ("final_answer", {"answer": "done"}),
        ]
    )


def _profile() -> ProfileSchema:
    return ProfileSchema(
        name="Petr",
        goals=["Run a half marathon under 2h"],
        preferred_sports=[SportType.RUNNING, SportType.STRENGTH],
        weekly_target_hours=6.0,
        constraints=["No gym on Tuesdays"],
        narrative="Recreational athlete, runs 3x/week, lifts 2x/week.",
    )


def _recent_activities() -> list[ActivitySchema]:
    return [
        ActivitySchema(
            title="Easy morning run",
            sport=SportType.RUNNING,
            activity_date=TODAY - timedelta(days=1),
            duration_minutes=35,
            rpe=4,
        ),
        ActivitySchema(
            title="Push day",
            sport=SportType.STRENGTH,
            activity_date=TODAY - timedelta(days=3),
            duration_minutes=60,
            rpe=7,
        ),
    ]


def _seven_day_plan(week_start: date) -> dict[str, Any]:
    sports = [
        ("running", "Easy run", "Z2 easy 35 min", "low"),
        ("strength", "Lower body", "Squats, RDLs, 4x6", "high"),
        ("running", "Tempo", "20 min tempo + warmup/cooldown", "high"),
        ("yoga", "Mobility", "30 min mobility flow", "low"),
        ("running", "Long run", "75 min steady", "medium"),
        ("strength", "Upper body", "Bench, rows, 4x6", "medium"),
        ("running", "Recovery jog", "30 min easy", "low"),
    ]
    return {
        "week_start": week_start.isoformat(),
        "activities": [
            {
                "day": (week_start + timedelta(days=i)).isoformat(),
                "sport": sport,
                "title": title,
                "description": desc,
                "duration_minutes": 45,
                "intensity": intensity,
                "completed": False,
            }
            for i, (sport, title, desc, intensity) in enumerate(sports)
        ],
        "rationale": "Hard/easy alternation around the long run on Friday.",
    }


# --- generate_plan ---------------------------------------------------------


def test_generate_plan_returns_seven_day_plan() -> None:
    model = _submit_plan_then_finish(_seven_day_plan(NEXT_MONDAY))

    result = generate_plan(
        _profile(), _recent_activities(), NEXT_MONDAY, today=TODAY, model=model
    )

    assert result.plan is not None
    assert result.plan.week_start == NEXT_MONDAY
    assert len(result.plan.activities) == 7
    assert result.plan.activities[0].sport == SportType.RUNNING.value
    assert result.plan.activities[1].intensity == Intensity.HIGH.value
    assert result.fallback_message is None


def test_generate_plan_rejects_non_monday_week_start() -> None:
    not_monday = date(2026, 5, 20)  # Wednesday
    result = generate_plan(_profile(), [], not_monday, today=TODAY, model=ScriptedModel([]))
    assert result.plan is None
    assert result.fallback_message is not None
    assert "Monday" in result.fallback_message


def test_generate_plan_fallback_when_schema_invalid() -> None:
    bad_plan = _seven_day_plan(NEXT_MONDAY)
    bad_plan["week_start"] = "2026-05-20"  # Wednesday, fails PlanSchema validator
    model = _submit_plan_then_finish(bad_plan)
    result = generate_plan(
        _profile(), _recent_activities(), NEXT_MONDAY, today=TODAY, model=model
    )
    assert result.plan is None
    assert result.fallback_message is not None


def test_generate_plan_agent_exception_returns_fallback() -> None:
    class BoomModel(Model):
        def generate(self, *args: Any, **kwargs: Any) -> ChatMessage:
            raise RuntimeError("model down")

    result = generate_plan(
        _profile(), _recent_activities(), NEXT_MONDAY, today=TODAY, model=BoomModel()
    )
    assert result.plan is None
    assert result.fallback_message is not None


def test_generate_plan_handles_empty_history() -> None:
    model = _submit_plan_then_finish(_seven_day_plan(NEXT_MONDAY))
    result = generate_plan(_profile(), [], NEXT_MONDAY, today=TODAY, model=model)
    assert result.plan is not None
    assert len(result.plan.activities) == 7


# --- revise_plan -----------------------------------------------------------


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
        rationale="Two sessions to start the week.",
    )


def test_revise_plan_returns_updated_plan() -> None:
    current = _existing_plan()
    edited = current.model_dump(mode="json", exclude_none=True)
    # Move the strength session from Tuesday to Wednesday.
    edited["activities"][1]["day"] = (NEXT_MONDAY + timedelta(days=2)).isoformat()
    model = _submit_plan_then_finish(edited)

    result = revise_plan(
        current,
        "move Tuesday's strength session to Wednesday",
        today=TODAY,
        model=model,
    )
    assert result.plan is not None
    assert result.plan.activities[1].day == NEXT_MONDAY + timedelta(days=2)
    assert result.fallback_message is None


def test_revise_plan_empty_instruction_returns_current() -> None:
    current = _existing_plan()
    result = revise_plan(current, "  ", today=TODAY, model=ScriptedModel([]))
    assert result.plan == current
    assert result.fallback_message is not None


def test_revise_plan_invalid_payload_falls_back_to_current() -> None:
    current = _existing_plan()
    bad_plan = current.model_dump(mode="json", exclude_none=True)
    bad_plan["week_start"] = "2026-05-20"  # Wednesday
    model = _submit_plan_then_finish(bad_plan)

    result = revise_plan(current, "swap days", today=TODAY, model=model)
    assert result.plan == current
    assert result.fallback_message is not None


def test_revise_plan_agent_exception_falls_back_to_current() -> None:
    current = _existing_plan()

    class BoomModel(Model):
        def generate(self, *args: Any, **kwargs: Any) -> ChatMessage:
            raise RuntimeError("model down")

    result = revise_plan(current, "shorter please", today=TODAY, model=BoomModel())
    assert result.plan == current
    assert result.fallback_message is not None
