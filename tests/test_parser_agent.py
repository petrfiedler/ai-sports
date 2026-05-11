"""Tests for the Parser Agent.

These tests inject a stubbed smolagents ``Model`` that replays canned
tool-call sequences. Nothing here calls the real Anthropic API.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import pytest
from smolagents import Model
from smolagents.models import (
    ChatMessage,
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    MessageRole,
)

from src.agents.parser_agent import parse_activity, revise_activity
from src.models.schemas import ActivitySchema, Intensity, SportType


class ScriptedModel(Model):
    """Replays a fixed sequence of tool calls back to the agent.

    Each call to ``generate`` consumes one entry from ``script``.
    Entries are ``(tool_name, arguments_dict)`` tuples.
    """

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


def _submit_then_finish(
    activity: Optional[dict[str, Any]],
    follow_up_questions: Optional[list[dict[str, Any]]] = None,
) -> ScriptedModel:
    return ScriptedModel(
        [
            (
                "submit_activity",
                {"activity": activity, "follow_up_questions": follow_up_questions or []},
            ),
            ("final_answer", {"answer": "done"}),
        ]
    )


TODAY = date(2026, 5, 11)


# --- Golden cases per sport ------------------------------------------------


def test_parses_running_activity() -> None:
    model = _submit_then_finish(
        {
            "title": "Easy morning run",
            "sport": "running",
            "activity_date": "2026-05-10",
            "duration_minutes": 30,
            "rpe": 4,
            "intensity": "low",
            "metrics": {"distance_km": 5.2, "avg_pace": "5:45/km"},
        }
    )

    result = parse_activity("30 min easy run yesterday, ~5 km", today=TODAY, model=model)

    assert result.activity is not None
    assert result.activity.sport == SportType.RUNNING.value
    assert result.activity.duration_minutes == 30
    assert result.activity.activity_date == date(2026, 5, 10)
    assert result.activity.metrics is not None
    assert result.activity.metrics.distance_km == 5.2
    assert result.activity.intensity == Intensity.LOW.value
    assert result.questions == []
    assert result.fallback_message is None


def test_parses_bouldering_activity_with_notes() -> None:
    model = _submit_then_finish(
        {
            "title": "Indoor bouldering session",
            "sport": "bouldering",
            "activity_date": "2026-05-10",
            "duration_minutes": 90,
            "notes": "V4-V5 overhangs, sent two new problems",
            "rpe": 7,
        }
    )

    result = parse_activity(
        "Yesterday bouldering 90 min, V4-V5 overhangs", today=TODAY, model=model
    )

    assert result.activity is not None
    assert result.activity.sport == SportType.BOULDERING.value
    assert result.activity.notes is not None
    assert "V4" in result.activity.notes


def test_parses_strength_with_exercises_and_sets() -> None:
    model = _submit_then_finish(
        {
            "title": "Upper body push day",
            "sport": "strength",
            "activity_date": "2026-05-11",
            "duration_minutes": 60,
            "exercises": [
                {
                    "name": "Bench press",
                    "sets": [
                        {"reps": 8, "weight_kg": 80, "rest_seconds": 120},
                        {"reps": 6, "weight_kg": 85, "rest_seconds": 120},
                    ],
                },
                {
                    "name": "Plank",
                    "sets": [{"duration_seconds": 60}],
                },
            ],
        }
    )

    result = parse_activity(
        "Today gym 1h: bench 8x80, 6x85; plank 60s", today=TODAY, model=model
    )

    assert result.activity is not None
    assert result.activity.sport == SportType.STRENGTH.value
    assert len(result.activity.exercises) == 2
    assert result.activity.exercises[0].name == "Bench press"
    assert len(result.activity.exercises[0].sets) == 2
    assert result.activity.exercises[0].sets[0].weight_kg == 80
    assert result.activity.exercises[1].sets[0].duration_seconds == 60


def test_parses_swim_activity() -> None:
    model = _submit_then_finish(
        {
            "title": "Pool swim",
            "sport": "swimming",
            "activity_date": "2026-05-11",
            "duration_minutes": 45,
            "metrics": {"distance_km": 1.5},
        }
    )

    result = parse_activity("45 min swim today, 1500 m", today=TODAY, model=model)

    assert result.activity is not None
    assert result.activity.sport == SportType.SWIMMING.value
    assert result.activity.metrics is not None
    assert result.activity.metrics.distance_km == 1.5


# --- Follow-up questions ---------------------------------------------------


def test_follow_up_questions_are_surfaced() -> None:
    model = _submit_then_finish(
        {
            "title": "Run",
            "sport": "running",
            "activity_date": "2026-05-11",
            "duration_minutes": 40,
        },
        follow_up_questions=[
            {"field": "rpe", "question": "How hard did it feel on a 1-10 scale?"},
            {"field": "metrics.distance_km", "question": "Roughly how far did you go?"},
        ],
    )

    result = parse_activity("went for a run", today=TODAY, model=model)

    assert result.activity is not None
    assert len(result.questions) == 2
    assert result.questions[0].field == "rpe"


# --- Garbage input ---------------------------------------------------------


def test_unparseable_input_returns_fallback_message() -> None:
    model = _submit_then_finish(activity=None, follow_up_questions=[])

    result = parse_activity("asdf qwer 1234 ?!?", today=TODAY, model=model)

    assert result.activity is None
    assert result.questions == []
    assert result.fallback_message is not None


def test_empty_input_short_circuits_without_calling_model() -> None:
    model = _submit_then_finish(activity=None)

    result = parse_activity("   ", today=TODAY, model=model)

    assert result.activity is None
    assert result.fallback_message is not None
    assert model.call_count == 0


# --- Robustness ------------------------------------------------------------


def test_invalid_schema_payload_falls_back_gracefully() -> None:
    model = _submit_then_finish(
        {
            "title": "Run",
            "sport": "running",
            "activity_date": "2026-05-11",
            "duration_minutes": -5,
        }
    )

    result = parse_activity("a weird run", today=TODAY, model=model)

    assert result.activity is None
    assert result.fallback_message is not None


def test_agent_exception_does_not_propagate() -> None:
    class BoomModel(Model):
        def generate(self, *args: Any, **kwargs: Any) -> ChatMessage:
            raise RuntimeError("upstream model failure")

    result = parse_activity("30 min run today", today=TODAY, model=BoomModel())

    assert result.activity is None
    assert result.fallback_message is not None


# --- revise_activity -------------------------------------------------------


def _existing_run() -> ActivitySchema:
    return ActivitySchema(
        title="Morning run",
        sport=SportType.RUNNING,
        activity_date=date(2026, 5, 10),
        duration_minutes=30,
        rpe=4,
    )


def test_revise_returns_updated_activity() -> None:
    model = _submit_then_finish(
        {
            "title": "Morning run",
            "sport": "running",
            "activity_date": "2026-05-10",
            "duration_minutes": 45,
            "rpe": 4,
        }
    )

    result = revise_activity(
        _existing_run(),
        "actually it was 45 minutes",
        today=TODAY,
        model=model,
    )

    assert result.activity is not None
    assert result.activity.duration_minutes == 45
    assert result.activity.title == "Morning run"
    assert result.fallback_message is None


def test_revise_empty_instruction_returns_current() -> None:
    current = _existing_run()
    result = revise_activity(current, "   ", today=TODAY, model=ScriptedModel([]))
    assert result.activity == current
    assert result.fallback_message is not None


def test_revise_invalid_payload_falls_back_to_current() -> None:
    current = _existing_run()
    model = _submit_then_finish(
        {
            "title": "Morning run",
            "sport": "running",
            "activity_date": "2026-05-10",
            "duration_minutes": -5,
        }
    )
    result = revise_activity(current, "make it faster", today=TODAY, model=model)
    assert result.activity == current
    assert result.fallback_message is not None


def test_revise_agent_exception_falls_back_to_current() -> None:
    current = _existing_run()

    class BoomModel(Model):
        def generate(self, *args: Any, **kwargs: Any) -> ChatMessage:
            raise RuntimeError("model down")

    result = revise_activity(current, "shorter please", today=TODAY, model=BoomModel())
    assert result.activity == current
    assert result.fallback_message is not None
